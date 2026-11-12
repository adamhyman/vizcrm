from decimal import ROUND_HALF_UP, Decimal

from django.core.validators import MinValueValidator
from django.db import models

from apps.stores.models import Company, Store

CENT = Decimal('0.01')
NON_NEGATIVE = [MinValueValidator(Decimal('0'))]


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


class Section(models.Model):
    """Top-level product grouping, shown as a tab at order entry (Dry Cleaning, Laundry…)."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='sections')
    name = models.CharField(max_length=60)
    position = models.PositiveIntegerField(default=0)
    # Goods sold as-is (lint rollers, garment bags). Retail sales may only include these.
    retail = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['position', 'id']
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='unique_section_name_per_company'),
        ]

    def __str__(self):
        return self.name


class Product(models.Model):
    class PricingUnit(models.TextChoices):
        PIECE = 'piece', 'Per item'
        WEIGHT = 'weight', 'Per weight unit'

    section = models.ForeignKey(Section, on_delete=models.PROTECT, related_name='products')
    name = models.CharField(max_length=80)
    pricing_unit = models.CharField(max_length=10, choices=PricingUnit.choices, default=PricingUnit.PIECE)
    sku = models.CharField('ID / SKU', max_length=40, blank=True)
    position = models.PositiveIntegerField(default=0)
    # The POS tile: an image, and optional text drawn over it.
    button_image = models.ImageField(upload_to='product-buttons/', blank=True)
    overlay_text = models.CharField(max_length=30, blank=True)

    price = models.DecimalField(max_digits=10, decimal_places=2, validators=NON_NEGATIVE)
    # Blank means price × the store's express multiplier.
    express_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, validators=NON_NEGATIVE
    )
    cost_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, validators=NON_NEGATIVE
    )
    minimum_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, validators=NON_NEGATIVE
    )
    minimum_quantity = models.PositiveIntegerField(default=0)

    # Physical pieces per unit sold, e.g. a two-piece suit is 2. Drives tags and assembly.
    # Retail goods (lint rollers) are 0: they aren't garments to tag or track.
    pieces_per_unit = models.PositiveSmallIntegerField(default=1)
    # Added to the store turnaround when this product is on an order.
    extra_days = models.PositiveSmallIntegerField(default=0)

    active = models.BooleanField(default=True)
    available_online = models.BooleanField(default=True)
    # Open the item details screen (colors, damage…) when this product is added at order entry.
    request_item_details = models.BooleanField(default=False)
    # Price lists the product can be ordered on. Empty means all of them.
    price_lists = models.ManyToManyField(
        'PriceList', blank=True, related_name='products', verbose_name='active in price lists'
    )

    class Meta:
        ordering = ['section__position', 'position', 'id']
        constraints = [
            models.UniqueConstraint(fields=['section', 'name'], name='unique_product_name_per_section'),
        ]

    def __str__(self):
        return self.name

    @property
    def company(self):
        return self.section.company

    def offered_on(self, price_list):
        """Whether the product can be ordered on `price_list` (None = the products' own prices)."""
        if price_list is None or price_list.is_default:
            return True
        limited_to = {p.pk for p in self.price_lists.all()}
        return not limited_to or price_list.pk in limited_to

    def default_express_price(self, store: Store):
        if self.express_price is not None:
            return self.express_price
        return money(self.price * store.express_multiplier)


class PriceList(models.Model):
    """A named set of price overrides, e.g. for a business account or a customer group."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='price_lists')
    name = models.CharField(max_length=60)
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ['-is_default', 'name']
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='unique_price_list_name_per_company'),
            models.UniqueConstraint(
                fields=['company'], condition=models.Q(is_default=True), name='one_default_price_list_per_company'
            ),
        ]

    def __str__(self):
        return self.name


class PriceListItem(models.Model):
    price_list = models.ForeignKey(PriceList, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='price_list_items')
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=NON_NEGATIVE)
    # Blank means this list's price × the current store's express multiplier.
    express_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, validators=NON_NEGATIVE
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['price_list', 'product'], name='unique_product_per_price_list'),
        ]

    def __str__(self):
        return f'{self.price_list}: {self.product} {self.price}'


class Upcharge(models.Model):
    """An optional extra charge added to an item at order entry (stain treatment, leather…)."""

    class Kind(models.TextChoices):
        FIXED = 'fixed', 'Fixed amount'
        PERCENT = 'percent', 'Percent of item price'

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='upcharges')
    name = models.CharField(max_length=60)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.FIXED)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=NON_NEGATIVE)
    # Empty means the upcharge is offered on every product.
    products = models.ManyToManyField(Product, blank=True, related_name='upcharges')
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def amount_for(self, item_price):
        if self.kind == self.Kind.PERCENT:
            return money(item_price * self.amount / 100)
        return self.amount


class StoreProduct(models.Model):
    """One store's own price for a product, or that the store doesn't sell it.

    Blank prices fall back to the product's. Price lists still win over these.
    """

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='product_settings')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='store_settings')
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, validators=NON_NEGATIVE)
    express_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, validators=NON_NEGATIVE
    )
    available = models.BooleanField(default=True, help_text='Untick if this store does not sell the product.')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['store', 'product'], name='unique_product_setting_per_store'),
        ]

    def __str__(self):
        return f'{self.store}: {self.product}'
