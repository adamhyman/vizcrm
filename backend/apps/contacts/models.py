import re
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.catalog.models import PriceList
from apps.stores.models import Company, Store, hex_color


def phone_digits(value):
    return re.sub(r'\D', '', value)


class CustomerGroup(models.Model):
    """A named set of customers, used for pricing and marketing audiences.

    Members are assigned by hand for now; rule-based groups come with marketing.
    """

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='customer_groups')
    name = models.CharField(max_length=60)
    color = models.CharField(max_length=7, blank=True, validators=[hex_color])
    # Flag members with the group's color when they are picked at order entry.
    highlight_in_pos = models.BooleanField(default=False)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='unique_customer_group_name_per_company'),
        ]

    def __str__(self):
        return self.name


class BusinessAccount(models.Model):
    """A business whose orders are billed together, e.g. a hotel."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='business_accounts')
    name = models.CharField(max_length=120)
    contact_name = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    billing_address = models.TextField(blank=True)
    # Default for the business's customers that have no price list of their own.
    price_list = models.ForeignKey(
        PriceList, on_delete=models.SET_NULL, null=True, blank=True, related_name='business_accounts'
    )
    notes = models.TextField(blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='unique_business_account_name_per_company'),
        ]

    def __str__(self):
        return self.name


class Customer(models.Model):
    class NotificationMethod(models.TextChoices):
        DEFAULT = 'default', "Store's default"
        SMS = 'sms', 'SMS'
        EMAIL = 'email', 'Email'
        NONE = 'none', "Don't notify"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='customers')
    # Where the customer was added; they can use any of the company's stores.
    home_store = models.ForeignKey(Store, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    first_name = models.CharField(max_length=60)
    last_name = models.CharField(max_length=60, blank=True)
    # Whether phone / email / an address are required is a store setting.
    phone = models.CharField(max_length=40, blank=True)
    # Digits of `phone`, kept in sync on save, for searching by any part of the number.
    phone_digits = models.CharField(max_length=40, editable=False, db_index=True)
    email = models.EmailField(blank=True)
    notification_method = models.CharField(
        max_length=10, choices=NotificationMethod.choices, default=NotificationMethod.DEFAULT
    )
    marketing_opt_in = models.BooleanField(default=False)

    # Address, used for pickup & delivery
    street_address = models.CharField(max_length=200, blank=True)
    unit = models.CharField('apt / suite / unit', max_length=40, blank=True)
    city = models.CharField(max_length=100, blank=True)
    region = models.CharField('state / region', max_length=100, blank=True)
    postal_code = models.CharField('zip / postal code', max_length=20, blank=True)
    # Filled from address lookup; used for delivery zones and the driver map.
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    # Gate code, parking, where to leave bags…
    driver_instructions = models.TextField(blank=True)

    # Billing
    business = models.ForeignKey(
        BusinessAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='customers'
    )
    # Blank means the business account's price list, else the store default.
    price_list = models.ForeignKey(
        PriceList, on_delete=models.SET_NULL, null=True, blank=True, related_name='customers'
    )
    discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('100'))],
    )

    groups = models.ManyToManyField(CustomerGroup, blank=True, related_name='customers')
    # Care preferences, e.g. "light starch, shirts on hangers".
    preferences = models.TextField(blank=True)
    # Shown to staff wherever the customer appears, e.g. at order entry.
    notes = models.TextField(blank=True)
    # Never shown outside the back office (e.g. not in the customer app).
    private_notes = models.TextField(blank=True)

    # The company's anonymous "Retail customer", used for retail sales to walk-ins.
    walk_in = models.BooleanField(default=False, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['last_name', 'first_name', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['company'], condition=models.Q(walk_in=True), name='one_walk_in_customer_per_company'
            ),
        ]

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()

    @classmethod
    def walk_in_for(cls, company):
        customer, _ = cls.objects.get_or_create(
            company=company, walk_in=True, defaults={'first_name': 'Retail customer'}
        )
        return customer

    def effective_price_list(self, store=None):
        """The price list for this customer's orders at `store`; None means the products' own prices.

        Their own, else their business account's, else the store's default price list.
        """
        if self.price_list_id:
            return self.price_list
        if self.business_id and self.business.price_list_id:
            return self.business.price_list
        return store.default_price_list if store else None

    def save(self, *args, **kwargs):
        self.phone_digits = phone_digits(self.phone)
        if kwargs.get('update_fields') is not None and 'phone' in kwargs['update_fields']:
            kwargs['update_fields'] = {*kwargs['update_fields'], 'phone_digits'}
        super().save(*args, **kwargs)
