from rest_framework import serializers

from apps.stores.scoping import CompanyScopedPrimaryKeyField

from .models import PriceList, PriceListItem, Product, Section, StoreProduct, Upcharge
from .services import MONEY_OPS, unit_price


class SectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Section
        fields = ['id', 'name', 'position', 'retail', 'active']


class ProductSerializer(serializers.ModelSerializer):
    section = CompanyScopedPrimaryKeyField(queryset=Section.objects.all())
    # Empty means the product can be ordered on every price list.
    price_lists = CompanyScopedPrimaryKeyField(queryset=PriceList.objects.all(), many=True, required=False)
    # Prices at the current store, after the price list chosen with ?price_list=, if any.
    effective_price = serializers.SerializerMethodField()
    effective_express_price = serializers.SerializerMethodField()
    # Whether the current store sells it.
    available_here = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'section', 'name', 'pricing_unit', 'sku', 'position',
            'price', 'express_price', 'cost_price', 'minimum_price', 'minimum_quantity',
            'pieces_per_unit', 'extra_days', 'active', 'available_online', 'request_item_details',
            'price_lists', 'button_image', 'overlay_text',
            'effective_price', 'effective_express_price', 'available_here',
        ]

    def _store_setting(self, product):
        return self.context.get('store_settings', {}).get(product.pk)

    def _unit_price(self, product):
        store = self.context['request'].store
        return unit_price(product, store, self.context.get('price_overrides'), self._store_setting(product))

    def get_available_here(self, product) -> bool:
        setting = self._store_setting(product)
        return setting is None or setting.available

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
            company = self.context['request'].company
            others = PriceList.objects.filter(company=company, is_default=True)
            if self.instance:
                others = others.exclude(pk=self.instance.pk)
            if others.exists():
                raise serializers.ValidationError('Your company already has a default price list.')
        return value


class PriceListItemSerializer(serializers.ModelSerializer):
    price_list = CompanyScopedPrimaryKeyField(queryset=PriceList.objects.all())
    product = CompanyScopedPrimaryKeyField(queryset=Product.objects.all(), company_lookup='section__company')

    class Meta:
        model = PriceListItem
        fields = ['id', 'price_list', 'product', 'price', 'express_price']

    def validate_price_list(self, price_list):
        if price_list.is_default:
            raise serializers.ValidationError(
                'The default price list uses the products\' own prices; edit the product instead.'
            )
        return price_list


class StoreProductSerializer(serializers.ModelSerializer):
    """The current store's own price for a product, or that it doesn't sell it."""

    product = CompanyScopedPrimaryKeyField(queryset=Product.objects.all(), company_lookup='section__company')

    class Meta:
        model = StoreProduct
        fields = ['id', 'product', 'price', 'express_price', 'available']

    def validate_product(self, product):
        existing = StoreProduct.objects.filter(store=self.context['request'].store, product=product)
        if self.instance:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError('This store already has settings for that product; edit them.')
        return product


class UpchargeSerializer(serializers.ModelSerializer):
    products = CompanyScopedPrimaryKeyField(
        queryset=Product.objects.all(), company_lookup='section__company', many=True, required=False
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
    request_item_details = serializers.DictField(child=serializers.BooleanField(), required=False)

    def validate(self, attrs):
        for field in ('extra_days', 'active', 'available_online', 'request_item_details'):
            if field in attrs and set(attrs[field]) != {'value'}:
                raise serializers.ValidationError({field: 'Expected {"value": ...}.'})
        return attrs


class BulkUpdateSerializer(serializers.Serializer):
    products = CompanyScopedPrimaryKeyField(
        queryset=Product.objects.select_related('section__company'), company_lookup='section__company', many=True
    )
    price_list = CompanyScopedPrimaryKeyField(queryset=PriceList.objects.all(), required=False, allow_null=True)
    changes = BulkUpdateChangesSerializer()
    # False returns a preview of old → new values without saving.
    apply = serializers.BooleanField(default=False)
