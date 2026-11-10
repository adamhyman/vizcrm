import datetime

from django import forms
from django.contrib import admin

from .models import BusinessHours, ClosedDate, Shift, Station, Store, TaxRate, Weekday, timezone_choices


def hour_label(value):
    """12am, 1am … 11pm (with minutes if not on the hour, e.g. 5:30pm)."""
    hour = value.hour % 12 or 12
    minutes = f':{value.minute:02d}' if value.minute else ''
    return f"{hour}{minutes}{'am' if value.hour < 12 else 'pm'}"


HOUR_CHOICES = [(str(datetime.time(h)), hour_label(datetime.time(h))) for h in range(24)]


class MultiSelectDropdown(forms.SelectMultiple):
    """A multi-select shown as a dropdown with removable tags (the admin's bundled Select2)."""

    def __init__(self, placeholder='', attrs=None, choices=()):
        super().__init__(attrs={'data-multi-select': '', 'data-placeholder': placeholder, **(attrs or {})},
                         choices=choices)

    class Media:
        css = {'all': ['admin/css/vendor/select2/select2.min.css', 'admin/css/autocomplete.css']}
        js = [
            'admin/js/vendor/jquery/jquery.min.js',
            'admin/js/vendor/select2/select2.full.min.js',
            'admin/js/jquery.init.js',
            'stores/admin/multi-select.js',
        ]


class StoreForm(forms.ModelForm):
    timezone = forms.ChoiceField(choices=timezone_choices)
    ready_time = forms.TypedChoiceField(choices=HOUR_CHOICES, coerce=datetime.time.fromisoformat)
    cutoff_time = forms.TypedChoiceField(
        label='Cutoff time',
        choices=[('', 'No cutoff'), *HOUR_CHOICES],
        coerce=datetime.time.fromisoformat,
        empty_value=None,
        required=False,
        help_text='Items dropped off after this time will add an extra day.',
    )
    express_ready_time = forms.TypedChoiceField(
        label='Express ready time',
        choices=[('', 'Same as ready time'), *HOUR_CHOICES],
        coerce=datetime.time.fromisoformat,
        empty_value=None,
        required=False,
    )
    turnaround_excluded_weekdays = forms.TypedMultipleChoiceField(
        label='Exclude days',
        choices=Weekday.choices,
        coerce=int,
        required=False,
        widget=MultiSelectDropdown(placeholder='None'),
        help_text="Days that don't count towards turnaround, e.g. Sunday.",
    )

    class Meta:
        model = Store
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tz = self.instance.timezone if self.instance.pk else self.fields['timezone'].initial
        ready = self.fields['ready_time']
        tz_label = tz.replace('_', ' ')
        ready.help_text = f"In the store's timezone ({tz_label})."
        self.fields['express_ready_time'].help_text = (
            f"In the store's timezone ({tz_label}). Leave as \"Same as ready time\" to use the ready time."
        )
        # Keep an existing off-the-hour time selectable rather than silently changing it.
        for name in ('ready_time', 'cutoff_time', 'express_ready_time'):
            current = getattr(self.instance, name)
            field = self.fields[name]
            if current and str(current) not in dict(field.choices):
                blank = [c for c in field.choices if c[0] == '']
                timed = [c for c in field.choices if c[0] != '']
                field.choices = blank + sorted([*timed, (str(current), hour_label(current))])
        if not self.instance.pk:
            self.initial.setdefault('ready_time', str(Store._meta.get_field('ready_time').default))


class StationInline(admin.TabularInline):
    model = Station
    extra = 0


class TaxRateInline(admin.TabularInline):
    model = TaxRate
    extra = 0
    max_num = 3


class BusinessHoursInline(admin.TabularInline):
    model = BusinessHours
    extra = 0


class ShiftInline(admin.TabularInline):
    model = Shift
    extra = 0


class ClosedDateInline(admin.TabularInline):
    model = ClosedDate
    extra = 0


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    form = StoreForm
    list_display = ('name', 'city', 'phone', 'timezone', 'turnaround_days')
    fieldsets = (
        ('Name & location', {'fields': (
            'name', 'street_address', 'city', 'region', 'postal_code', 'country', 'latitude', 'longitude',
        )}),
        ('Contact', {'fields': ('phone', 'email', 'website')}),
        ('Branding', {'fields': ('logo', 'brand_color', 'logo_background_color')}),
        ('Localization', {'fields': ('language', 'timezone', 'currency', 'weight_unit', 'distance_unit')}),
        ('Tax', {'fields': ('tax_mode', 'tax_id')}),
        ('Turnaround', {'fields': (
            'turnaround_days', 'ready_time', 'cutoff_time',
            'express_turnaround_days', 'express_ready_time',
            'turnaround_excluded_weekdays',
        )}),
        ('Pricing & production', {'fields': ('express_multiplier', 'rack_slot_count')}),
        ('Security', {'fields': ('allowed_ips',)}),
    )
    inlines = [StationInline, TaxRateInline, BusinessHoursInline, ShiftInline, ClosedDateInline]
