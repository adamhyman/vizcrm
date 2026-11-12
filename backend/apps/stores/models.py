import datetime
import ipaddress
import zoneinfo
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models

hex_color = RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Use a hex color like #1A73E8.')


def validate_timezone(value):
    if value not in zoneinfo.available_timezones():
        raise ValidationError(f'{value!r} is not a known timezone.')


def timezone_choices():
    return [(name, name.replace('_', ' ')) for name in sorted(zoneinfo.available_timezones())]


def validate_weekdays(value):
    if not isinstance(value, list) or any(not isinstance(d, int) or not 0 <= d <= 6 for d in value):
        raise ValidationError('Use a list of weekday numbers, 0 = Monday … 6 = Sunday.')
    if len(set(value)) == 7:
        raise ValidationError('At least one day must count towards turnaround.')


def validate_ip_allowlist(value):
    for entry in value.split():
        try:
            ipaddress.ip_network(entry, strict=False)
        except ValueError as exc:
            raise ValidationError(f'{entry!r} is not an IP address or range.') from exc


class Weekday(models.IntegerChoices):
    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


CUSTOMER_FIELD_CHOICES = [('phone', 'Telephone number'), ('email', 'Email'), ('address', 'Address')]


def validate_customer_fields(value):
    allowed = {key for key, _ in CUSTOMER_FIELD_CHOICES}
    if not isinstance(value, list) or not set(value) <= allowed:
        raise ValidationError(f"Use a list of: {', '.join(sorted(allowed))}.")


def default_customer_required_fields():
    return ['phone']


class Company(models.Model):
    """A business with one or more stores. Its stores share the catalog and customers."""

    name = models.CharField(max_length=120)
    primary_contact = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)

    class Meta:
        verbose_name_plural = 'companies'

    def __str__(self):
        return self.name


class Store(models.Model):
    class DetailingOrders(models.TextChoices):
        QUICK_DROP = 'quick_drop', 'Only Quick Drop orders'
        ALL = 'all', 'All orders'

    class TaxMode(models.TextChoices):
        EXCLUSIVE = 'exclusive', 'Added on top of product price'
        INCLUSIVE = 'inclusive', 'Included in product price'

    class WeightUnit(models.TextChoices):
        LB = 'lb', 'Pounds'
        KG = 'kg', 'Kilograms'

    class DistanceUnit(models.TextChoices):
        IMPERIAL = 'imperial', 'Miles / feet'
        METRIC = 'metric', 'Kilometres / metres'

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name='stores')

    # Name & location
    name = models.CharField(max_length=120)
    street_address = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100, blank=True)
    region = models.CharField('state / region', max_length=100, blank=True)
    postal_code = models.CharField('zip / postal code', max_length=20, blank=True)
    country = models.CharField(max_length=2, default='US', help_text='ISO country code, e.g. US.')
    # Places the store on the map in the customer and driver apps.
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )

    # Contact
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)

    # Express price for products without their own express price.
    express_multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal('1.50'))

    # Branding
    logo = models.ImageField(upload_to='store-logos/', blank=True)
    brand_color = models.CharField(max_length=7, blank=True, validators=[hex_color])
    # Shown behind the logo on receipts, emails and the lock screen.
    logo_background_color = models.CharField(max_length=7, blank=True, validators=[hex_color])

    # Localization
    language = models.CharField(max_length=10, default='en')
    timezone = models.CharField(max_length=64, default='America/Los_Angeles', validators=[validate_timezone])
    currency = models.CharField(max_length=3, default='USD')
    weight_unit = models.CharField(max_length=2, choices=WeightUnit.choices, default=WeightUnit.LB)
    distance_unit = models.CharField(max_length=10, choices=DistanceUnit.choices, default=DistanceUnit.IMPERIAL)

    # Tax
    tax_mode = models.CharField(max_length=20, choices=TaxMode.choices, default=TaxMode.EXCLUSIVE)
    tax_id = models.CharField('tax / VAT ID', max_length=60, blank=True)

    # Turnaround: due date = drop-off + N counted days, at the ready time.
    turnaround_days = models.PositiveSmallIntegerField(default=2)
    ready_time = models.TimeField(default=datetime.time(17, 0), help_text="In the store's timezone.")
    # Drop-offs at or after this time count from the next day. Blank means no cutoff.
    cutoff_time = models.TimeField(
        null=True, blank=True, help_text='Items dropped off after this time will add an extra day.'
    )
    # Blank means express orders use the normal turnaround.
    express_turnaround_days = models.PositiveSmallIntegerField(null=True, blank=True)
    # Blank means express orders are ready at the normal ready time.
    express_ready_time = models.TimeField(
        null=True, blank=True, help_text="In the store's timezone. Blank means the same as the ready time."
    )
    # Weekdays that don't count towards turnaround (0 = Monday … 6 = Sunday).
    turnaround_excluded_weekdays = models.JSONField(default=list, blank=True, validators=[validate_weekdays])

    # Pricing
    # For customers with no price list of their own (or from their business). Blank means product prices.
    default_price_list = models.ForeignKey(
        'catalog.PriceList', on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    # A customer's first order gets this discount, or their own discount if that's bigger.
    first_order_discount_percent = models.DecimalField(
        'first order discount (%)', max_digits=5, decimal_places=2, default=Decimal('0'),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    # Orders under these amounts (before discount) are charged up to them. Not applied to retail sales.
    minimum_order_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0'), validators=[MinValueValidator(0)]
    )
    minimum_express_order_amount = models.DecimalField(
        'minimum order amount for express', max_digits=10, decimal_places=2, default=Decimal('0'),
        validators=[MinValueValidator(0)],
    )

    # Order cleaned / collected: what staff must enter.
    require_rack_when_cleaned = models.BooleanField('prompt for storage rack location', default=True)
    require_bags_when_cleaned = models.BooleanField('prompt for number of bags and hanging items', default=False)
    reweigh_when_cleaned = models.BooleanField('prompt to re-weigh weight products when cleaned', default=False)
    reweigh_when_collected = models.BooleanField('prompt to re-weigh weight products when collected', default=False)
    # Hide orders from the order board after this many days. Blank means never.
    archive_ready_after_days = models.PositiveSmallIntegerField(
        'archive ready orders after (days)', null=True, blank=True
    )
    archive_collected_after_days = models.PositiveSmallIntegerField(
        'archive collected orders after (days)', null=True, blank=True
    )

    # Production
    rack_slot_count = models.PositiveIntegerField(default=50)

    # Detailing: an optional first stage where staff itemise and check orders before cleaning.
    detailing_enabled = models.BooleanField('use detailing stage', default=True)
    # Quick Drop orders are itemised in Detailing, so they need it on.
    quick_drop_enabled = models.BooleanField(
        'enable Quick Drop', default=True, help_text='Take in orders without itemising them at drop-off.'
    )
    # Lets staff edit an order from the Detailing tab before detailing it.
    detailing_show_edit_button = models.BooleanField('show edit button in detailing', default=False)
    detailing_orders = models.CharField(
        'in-store orders to send to detailing', max_length=20,
        choices=DetailingOrders.choices, default=DetailingOrders.QUICK_DROP,
    )
    # When sending all in-store orders: only those with an item in one of these sections. Empty means any.
    detailing_sections = models.ManyToManyField(
        'catalog.Section', blank=True, related_name='+', verbose_name='limit detailing to sections'
    )

    # Customers: what staff must enter when creating a customer (a name always is).
    customer_required_fields = models.JSONField(
        default=default_customer_required_fields, blank=True, validators=[validate_customer_fields]
    )

    # Security: staff may only use the system from these IPs / ranges (one per line).
    # Empty means no restriction.
    allowed_ips = models.TextField(blank=True, validators=[validate_ip_allowlist])

    def __str__(self):
        return self.name

    def clean(self):
        if self.quick_drop_enabled and not self.detailing_enabled:
            raise ValidationError({'quick_drop_enabled': 'Quick Drop needs the detailing stage, where its items are added.'})

    @property
    def tz(self):
        return zoneinfo.ZoneInfo(self.timezone)

    def allowed_networks(self):
        return [ipaddress.ip_network(entry, strict=False) for entry in self.allowed_ips.split()]


class Station(models.Model):
    """A till / register within a store. Cash-ups happen per station."""

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='stations')
    name = models.CharField(max_length=60)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['store', 'name'], name='unique_station_name_per_store'),
        ]

    def __str__(self):
        return f'{self.store} – {self.name}'


class TaxRate(models.Model):
    """Up to three named tax rates per store, applied in position order."""

    class Position(models.IntegerChoices):
        FIRST = 1
        SECOND = 2
        THIRD = 3

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='tax_rates')
    position = models.PositiveSmallIntegerField(choices=Position.choices)
    name = models.CharField(max_length=60)
    rate = models.DecimalField('rate (%)', max_digits=6, decimal_places=3)

    class Meta:
        ordering = ['position']
        constraints = [
            models.UniqueConstraint(fields=['store', 'position'], name='unique_tax_position_per_store'),
        ]

    def __str__(self):
        return f'{self.name} ({self.rate}%)'


class TimeRange(models.Model):
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    starts_at = models.TimeField()
    ends_at = models.TimeField()

    class Meta:
        abstract = True
        ordering = ['weekday', 'starts_at']

    def clean(self):
        if self.starts_at is not None and self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValidationError({'ends_at': 'Must be after the start time.'})


class BusinessHours(TimeRange):
    """An opening period. A weekday with no periods is closed; several periods allow a lunch break."""

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='business_hours')

    class Meta(TimeRange.Meta):
        verbose_name_plural = 'business hours'

    def __str__(self):
        return f'{self.get_weekday_display()} {self.starts_at:%H:%M}–{self.ends_at:%H:%M}'


class Shift(TimeRange):
    """A named staff shift, e.g. "Morning" on Mondays 7:00–15:00."""

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='shifts')
    name = models.CharField(max_length=60)

    def __str__(self):
        return f'{self.name} ({self.get_weekday_display()} {self.starts_at:%H:%M}–{self.ends_at:%H:%M})'


class ClosedDate(models.Model):
    """A day the store is closed (holiday, refit). Skipped when calculating due dates."""

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='closed_dates')
    date = models.DateField()
    reason = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ['date']
        constraints = [
            models.UniqueConstraint(fields=['store', 'date'], name='unique_closed_date_per_store'),
        ]

    def __str__(self):
        return f'{self.date:%Y-%m-%d} {self.reason}'.strip()
