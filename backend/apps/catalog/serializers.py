from rest_framework import serializers

from apps.stores.scoping import StoreScopedPrimaryKeyField

from .models import PriceList, PriceListItem, Product, Section, Upcharge
from .services import MONEY_OPS, unit_price


class SectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Section
        fields = ['id', 'name', 'position', 'active']


class ProductSerializer(serializers.ModelSerializer):
    section = StoreScopedPrimaryKeyField(queryset=Section.objects.all())
    # Prices after applying the price list chosen with ?price_list=, if any.
    effective_price = serializers.SerializerMethodField()
    effective_express_price = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'section', 'name', 'pricing_unit', 'sku', 'position',
            'price', 'express_price', 'cost_price', 'minimum_price', 'minimum_quantity',
            'pieces_per_unit', 'extra_days', 'active', 'available_online',
            'effective_price', 'effective_express_price',
        ]

    def _unit_price(self, product):
        return unit_price(product, self.context.get('price_overrides'))

    def get_effective_price(self, product) -> str:
        return f'{self._unit_price(product).price:.2f}'

    def get_effective_express_price(self, product) -> str:
        return f'{self._unit_price(product).express_price:.2f}'


class PriceListSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceList
        fields = ['id', 'name', 'is_default']

    def validate_is_default(self, value):
        if value:
            store = self.context['request'].user.store
            others = PriceList.objects.filter(store=store, is_default=True)
            if self.instance:
                others = others.exclude(pk=self.instance.pk)
            if others.exists():
                raise serializers.ValidationError('This store already has a default price list.')
        return value


class PriceListItemSerializer(serializers.ModelSerializer):
    price_list = StoreScopedPrimaryKeyField(queryset=PriceList.objects.all())
    product = StoreScopedPrimaryKeyField(queryset=Product.objects.all(), store_lookup='section__store')

    class Meta:
        model = PriceListItem
        fields = ['id', 'price_list', 'product', 'price', 'express_price']

    def validate_price_list(self, price_list):
        if price_list.is_default:
            raise serializers.ValidationError(
                'The default price list uses the products\' own prices; edit the product instead.'
            )
        return price_list


class UpchargeSerializer(serializers.ModelSerializer):
    products = StoreScopedPrimaryKeyField(
        queryset=Product.objects.all(), store_lookup='section__store', many=True, required=False
    )

    class Meta:
        model = Upcharge
        fields = ['id', 'name', 'kind', 'amount', 'products', 'active']


class MoneyChangeSerializer(serializers.Serializer):
    op = serializers.ChoiceField(choices=MONEY_OPS)
    value = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)


class BulkUpdateChangesSerializer(serializers.Serializer):
    price = MoneyChangeSerializer(required=False)
    express_price = MoneyChangeSerializer(required=False)
    cost_price = MoneyChangeSerializer(required=False)
    minimum_price = MoneyChangeSerializer(required=False)
    extra_days = serializers.DictField(child=serializers.IntegerField(min_value=0), required=False)
    active = serializers.DictField(child=serializers.BooleanField(), required=False)
    available_online = serializers.DictField(child=serializers.BooleanField(), required=False)

    def validate(self, attrs):
        for field in ('extra_days', 'active', 'available_online'):
            if field in attrs and set(attrs[field]) != {'value'}:
                raise serializers.ValidationError({field: 'Expected {"value": ...}.'})
        return attrs


class BulkUpdateSerializer(serializers.Serializer):
    products = StoreScopedPrimaryKeyField(
        queryset=Product.objects.select_related('section__store'), store_lookup='section__store', many=True
    )
    price_list = StoreScopedPrimaryKeyField(queryset=PriceList.objects.all(), required=False, allow_null=True)
    changes = BulkUpdateChangesSerializer()
    # False returns a preview of old → new values without saving.
    apply = serializers.BooleanField(default=False)
