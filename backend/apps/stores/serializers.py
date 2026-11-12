from rest_framework import serializers

from apps.catalog.models import PriceList, Section

from .models import BusinessHours, ClosedDate, Company, Shift, Station, Store, TaxRate


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ['id', 'name', 'primary_contact', 'phone', 'email', 'website']


class StoreChoiceSerializer(serializers.ModelSerializer):
    """A store the signed-in user may work at."""

    class Meta:
        model = Store
        fields = ['id', 'name', 'city']


class StoreSerializer(serializers.ModelSerializer):
    detailing_sections = serializers.PrimaryKeyRelatedField(
        queryset=Section.objects.all(), many=True, required=False
    )
    default_price_list = serializers.PrimaryKeyRelatedField(
        queryset=PriceList.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = Store
        read_only_fields = ['company']
        fields = [
            'id', 'company', 'name', 'street_address', 'city', 'region', 'postal_code', 'country',
            'latitude', 'longitude', 'phone', 'email', 'website',
            'express_multiplier',
            'logo', 'brand_color', 'logo_background_color',
            'language', 'timezone', 'currency', 'weight_unit', 'distance_unit',
            'tax_mode', 'tax_id',
            'turnaround_days', 'ready_time', 'cutoff_time',
            'express_turnaround_days', 'express_ready_time',
            'turnaround_excluded_weekdays',
            'default_price_list', 'first_order_discount_percent',
            'minimum_order_amount', 'minimum_express_order_amount',
            'require_rack_when_cleaned', 'require_bags_when_cleaned', 'reweigh_when_cleaned',
            'reweigh_when_collected', 'archive_ready_after_days', 'archive_collected_after_days',
            'rack_slot_count',
            'detailing_enabled', 'quick_drop_enabled', 'detailing_orders', 'detailing_sections',
            'detailing_show_edit_button',
            'customer_required_fields', 'allowed_ips',
        ]

    def validate_default_price_list(self, price_list):
        if price_list is not None and price_list.company_id != self.instance.company_id:
            raise serializers.ValidationError("Choose one of your company's price lists.")
        return price_list

    def validate_detailing_sections(self, sections):
        if any(section.company_id != self.instance.company_id for section in sections):
            raise serializers.ValidationError("Choose sections from your company's catalog.")
        return sections

    def validate(self, attrs):
        detailing = attrs.get('detailing_enabled', self.instance.detailing_enabled)
        quick_drop = attrs.get('quick_drop_enabled', self.instance.quick_drop_enabled)
        if quick_drop and not detailing:
            raise serializers.ValidationError(
                {'quick_drop_enabled': 'Quick Drop needs the detailing stage, where its items are added.'}
            )
        return attrs


class StationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Station
        fields = ['id', 'name', 'active']


class TaxRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxRate
        fields = ['id', 'position', 'name', 'rate']

    def validate(self, attrs):
        position = attrs.get('position', getattr(self.instance, 'position', None))
        clash = TaxRate.objects.filter(store=self.context['request'].store, position=position)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError({'position': f'Tax {position} is already set.'})
        return attrs


class TimeRangeSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        starts = attrs.get('starts_at', getattr(self.instance, 'starts_at', None))
        ends = attrs.get('ends_at', getattr(self.instance, 'ends_at', None))
        if starts is not None and ends is not None and ends <= starts:
            raise serializers.ValidationError({'ends_at': 'Must be after the start time.'})
        return attrs


class BusinessHoursSerializer(TimeRangeSerializer):
    class Meta:
        model = BusinessHours
        fields = ['id', 'weekday', 'starts_at', 'ends_at']

    def validate(self, attrs):
        attrs = super().validate(attrs)
        weekday = attrs.get('weekday', getattr(self.instance, 'weekday', None))
        starts = attrs.get('starts_at', getattr(self.instance, 'starts_at', None))
        ends = attrs.get('ends_at', getattr(self.instance, 'ends_at', None))
        overlapping = BusinessHours.objects.filter(
            store=self.context['request'].store, weekday=weekday, starts_at__lt=ends, ends_at__gt=starts
        )
        if self.instance:
            overlapping = overlapping.exclude(pk=self.instance.pk)
        if overlapping.exists():
            raise serializers.ValidationError('Overlaps another opening period on the same day.')
        return attrs


class ShiftSerializer(TimeRangeSerializer):
    class Meta:
        model = Shift
        fields = ['id', 'name', 'weekday', 'starts_at', 'ends_at']


class ClosedDateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClosedDate
        fields = ['id', 'date', 'reason']

    def validate_date(self, value):
        clash = ClosedDate.objects.filter(store=self.context['request'].store, date=value)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError('This date is already marked closed.')
        return value


class DueDateQuerySerializer(serializers.Serializer):
    dropped_off_at = serializers.DateTimeField(required=False)
    express = serializers.BooleanField(default=False)
    extra_days = serializers.IntegerField(min_value=0, default=0)
