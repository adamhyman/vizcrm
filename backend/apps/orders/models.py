from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.catalog.models import NON_NEGATIVE, PriceList, Product, Section
from apps.contacts.models import Customer
from apps.stores.models import Company, Store

ZERO = Decimal('0.00')


def money_field(**kwargs):
    return models.DecimalField(max_digits=10, decimal_places=2, default=ZERO, validators=NON_NEGATIVE, **kwargs)


class Order(models.Model):
    class Type(models.TextChoices):
        IN_STORE = 'in_store', 'In-store'
        # Bags taken in without itemising; items are added in Detailing.
        QUICK_DROP = 'quick_drop', 'Quick Drop'
        # Goods sold over the counter; complete as soon as it's created.
        RETAIL = 'retail', 'Retail sale'

    class Status(models.TextChoices):
        DETAILING = 'detailing', 'Detailing'
        CLEANING = 'cleaning', 'Cleaning'
        READY = 'ready', 'Ready'
        COLLECTED = 'collected', 'Collected'

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='orders')
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='orders')
    # Shown to staff and customers as "Order #12"; counts up across the company's stores.
    number = models.PositiveIntegerField()
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='orders')
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.IN_STORE)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CLEANING)
    express = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    due_at = models.DateTimeField()

    # Pricing as it was when the order was priced. Blank price list means the products' own prices.
    price_list = models.ForeignKey(PriceList, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0'))
    subtotal = money_field()
    # Added when the subtotal is under the store's minimum order amount.
    minimum_charge = money_field()
    discount = money_field()
    # [{"name": "Sales Tax", "rate": "9.500", "amount": "1.43"}, …]
    taxes = models.JSONField(default=list, blank=True)
    tax = money_field()
    total = money_field()

    # Bags are counted at Quick Drop and when the order is marked cleaned; rack and hanging when cleaned.
    rack = models.CharField(max_length=20, blank=True)
    bags = models.PositiveSmallIntegerField(default=0)
    hanging = models.PositiveSmallIntegerField('hanging items', default=0)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    detailed_at = models.DateTimeField(null=True, blank=True)
    cleaned_at = models.DateTimeField(null=True, blank=True)
    collected_at = models.DateTimeField(null=True, blank=True)
    # Deleted orders are kept (for the deletions log, and so numbers aren't reused) but hidden.
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    deletion_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['-number']
        constraints = [
            models.UniqueConstraint(fields=['company', 'number'], name='unique_order_number_per_company'),
        ]

    def __str__(self):
        return f'#{self.number}'


class OrderItem(models.Model):
    """One garment or unit sold, e.g. "Suit 1" of three suits, or 6 lb of laundry."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    # Blank for a custom item.
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    section = models.ForeignKey(Section, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    name = models.CharField(max_length=80)
    # Weight in the store's weight unit, for weight-priced products; blank otherwise.
    weight = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal('0.01'))]
    )
    # Physical pieces this item counts as (a two-piece suit is 2).
    pieces = models.PositiveSmallIntegerField(default=1)

    # Per item, or per weight unit for weight-priced products.
    unit_price = money_field()
    # [{"name": "Stain Treatment", "amount": "3.00"}, …]
    upcharges = models.JSONField(default=list, blank=True)
    price = money_field()
    # True when staff typed the price instead of it being calculated.
    price_overridden = models.BooleanField(default=False)

    # Garment details; list values come from apps.orders.garments.
    colors = models.JSONField(default=list, blank=True)
    damages = models.JSONField(default=list, blank=True)
    stains = models.JSONField(default=list, blank=True)
    materials = models.JSONField(default=list, blank=True)
    patterns = models.JSONField(default=list, blank=True)
    styles = models.JSONField(default=list, blank=True)
    brand = models.CharField(max_length=60, blank=True)
    notes = models.TextField(blank=True)
    # The garment tag; scanned or typed.
    barcode = models.CharField(max_length=40, blank=True, db_index=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.name


class OrderIssue(models.Model):
    """A problem raised on an order (stain remaining, missing item…) until marked solved."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='issues')
    # The order's status when the issue was reported.
    stage = models.CharField(max_length=20, choices=Order.Status.choices)
    text = models.TextField()
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    reported_at = models.DateTimeField(auto_now_add=True)
    solved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    solved_at = models.DateTimeField(null=True, blank=True)
    # How it was resolved.
    resolution = models.TextField(blank=True)

    class Meta:
        ordering = ['-reported_at', '-id']

    def __str__(self):
        return f'{self.order}: {self.text[:40]}'

    @property
    def solved(self):
        return self.solved_at is not None


class OrderPhoto(models.Model):
    """A photo taken at order entry or later, e.g. of damage. Optionally of one item."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='photos')
    item = models.ForeignKey(OrderItem, on_delete=models.SET_NULL, null=True, blank=True, related_name='photos')
    image = models.ImageField(upload_to='order-photos/%Y/%m/')
    caption = models.CharField(max_length=200, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at', 'id']

    def __str__(self):
        return f'{self.order} photo {self.pk}'


class OrderEvent(models.Model):
    """An entry in an order's timeline."""

    class Kind(models.TextChoices):
        CREATED = 'created', 'Order created'
        EDITED = 'edited', 'Order edited'
        DETAILED = 'detailed', 'Detailed'
        CLEANED = 'cleaned', 'Marked cleaned'
        COLLECTED = 'collected', 'Collected'
        ISSUE_REPORTED = 'issue_reported', 'Issue reported'
        ISSUE_SOLVED = 'issue_solved', 'Issue solved'
        PHOTO_ADDED = 'photo_added', 'Photo added'
        DELETED = 'deleted', 'Order deleted'

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='events')
    kind = models.CharField(max_length=20, choices=Kind.choices)
    # Short detail, e.g. the rack, the issue text or what was edited.
    detail = models.TextField(blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']

    def __str__(self):
        return f'{self.order} {self.get_kind_display()}'


class OrderRevision(models.Model):
    """A snapshot of an order after it was created or edited, for the order edits log."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='revisions')
    created = models.BooleanField(default=False, help_text='The snapshot taken when the order was created.')
    summary = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=Order.Status.choices)
    total = money_field()
    discount = money_field()
    price_list = models.CharField(max_length=60, blank=True)
    due_at = models.DateTimeField()
    # What was changed, e.g. "Items" or "Notes, due date".
    changes = models.CharField(max_length=200, blank=True)
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    edited_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-edited_at', '-id']

    def __str__(self):
        return f'{self.order} at {self.edited_at:%Y-%m-%d %H:%M}'
