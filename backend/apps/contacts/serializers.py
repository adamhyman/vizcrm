from rest_framework import serializers

from apps.catalog.models import PriceList
from apps.stores.scoping import CompanyScopedPrimaryKeyField

from .models import BusinessAccount, Customer, CustomerGroup, phone_digits


class CustomerGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerGroup
        fields = ['id', 'name', 'color', 'highlight_in_pos']


class BusinessAccountSerializer(serializers.ModelSerializer):
    price_list = CompanyScopedPrimaryKeyField(queryset=PriceList.objects.all(), required=False, allow_null=True)

    class Meta:
        model = BusinessAccount
        fields = [
            'id', 'name', 'contact_name', 'phone', 'email', 'billing_address',
            'price_list', 'notes', 'active',
        ]


class CustomerSerializer(serializers.ModelSerializer):
    business = CompanyScopedPrimaryKeyField(queryset=BusinessAccount.objects.all(), required=False, allow_null=True)
    price_list = CompanyScopedPrimaryKeyField(queryset=PriceList.objects.all(), required=False, allow_null=True)
    groups = CompanyScopedPrimaryKeyField(queryset=CustomerGroup.objects.all(), many=True, required=False)
    full_name = serializers.CharField(read_only=True)
    # The price list orders at the current store will use: the customer's own, else the business's,
    # else the store's default.
    effective_price_list = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            'id', 'first_name', 'last_name', 'full_name', 'phone', 'email',
            'notification_method', 'marketing_opt_in',
            'street_address', 'unit', 'city', 'region', 'postal_code', 'latitude', 'longitude',
            'driver_instructions',
            'business', 'price_list', 'effective_price_list', 'discount_percent',
            'groups', 'preferences', 'notes', 'private_notes', 'walk_in', 'home_store', 'created_at', 'updated_at',
        ]
        read_only_fields = ['home_store']

    def get_effective_price_list(self, customer) -> int | None:
        price_list = customer.effective_price_list(self.context['request'].store)
        return price_list.pk if price_list else None

    def validate_phone(self, value):
        if value and not phone_digits(value):
            raise serializers.ValidationError('Enter a valid phone number.')
        return value

    def validate(self, attrs):
        required = self.context['request'].store.customer_required_fields
        # The 'address' setting requires a street address; the other address fields stay optional.
        checks = {'phone': 'phone', 'email': 'email', 'address': 'street_address'}
        errors = {}
        for setting, field in checks.items():
            if setting in required and not attrs.get(field, getattr(self.instance, field, '')):
                errors[field] = 'This store requires it for every customer.'
        if errors:
            raise serializers.ValidationError(errors)
        return attrs
