from rest_framework import serializers

from .models import BusinessHours, ClosedDate, Shift, Station, Store, TaxRate


class StoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Store
        fields = [
            'id', 'name', 'street_address', 'city', 'region', 'postal_code', 'country',
            'latitude', 'longitude', 'phone', 'email', 'website',
            'logo', 'brand_color', 'logo_background_color',
            'language', 'timezone', 'currency', 'weight_unit', 'distance_unit',
            'tax_mode', 'tax_id',
            'turnaround_days', 'ready_time', 'cutoff_time',
            'express_turnaround_days', 'express_ready_time',
            'turnaround_excluded_weekdays',
            'express_multiplier', 'rack_slot_count', 'customer_required_fields', 'allowed_ips',
        ]


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
        clash = TaxRate.objects.filter(store=self.context['request'].user.store, position=position)
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
            store=self.context['request'].user.store, weekday=weekday, starts_at__lt=ends, ends_at__gt=starts
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
        clash = ClosedDate.objects.filter(store=self.context['request'].user.store, date=value)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError('This date is already marked closed.')
        return value


class DueDateQuerySerializer(serializers.Serializer):
    dropped_off_at = serializers.DateTimeField(required=False)
    express = serializers.BooleanField(default=False)
    extra_days = serializers.IntegerField(min_value=0, default=0)
