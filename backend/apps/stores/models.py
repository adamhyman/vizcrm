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


class Store(models.Model):
    class TaxMode(models.TextChoices):
        EXCLUSIVE = 'exclusive', 'Added on top of product price'
        INCLUSIVE = 'inclusive', 'Included in product price'

    class WeightUnit(models.TextChoices):
        LB = 'lb', 'Pounds'
        KG = 'kg', 'Kilograms'

    class DistanceUnit(models.TextChoices):
        IMPERIAL = 'imperial', 'Miles / feet'
        METRIC = 'metric', 'Kilometres / metres'

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
    # Express price for products without their own express price.
    express_multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal('1.50'))

    # Production
    rack_slot_count = models.PositiveIntegerField(default=50)

    # Security: staff may only use the system from these IPs / ranges (one per line).
    # Empty means no restriction.
    allowed_ips = models.TextField(blank=True, validators=[validate_ip_allowlist])

    def __str__(self):
        return self.name

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
