from decimal import Decimal

from rest_framework import serializers

from apps.catalog.models import PriceList, Product, Section, Upcharge
from apps.contacts.models import Customer
from apps.stores.scoping import CompanyScopedPrimaryKeyField, StoreScopedPrimaryKeyField

from . import garments
from .models import Order, OrderEvent, OrderIssue, OrderItem, OrderPhoto, OrderRevision
from .services import NewItem, order_summary


def pick_list(field):
    return serializers.ListField(
        child=serializers.ChoiceField(choices=garments.LIST_FIELDS[field]),
        required=False, max_length=garments.MAX_CHOICES[field],
    )


class NewItemSerializer(serializers.Serializer):
    """An item at order entry: a catalog product, or a custom item with a name and price."""

    product = CompanyScopedPrimaryKeyField(
        queryset=Product.objects.select_related('section__company'), company_lookup='section__company',
        required=False, allow_null=True,
    )
    # Custom items only.
    name = serializers.CharField(max_length=80, required=False)
    section = CompanyScopedPrimaryKeyField(queryset=Section.objects.all(), required=False, allow_null=True)
    # Required for weight-priced products, in the store's weight unit.
    weight = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=Decimal('0.01'), required=False)
    upcharges = CompanyScopedPrimaryKeyField(
        queryset=Upcharge.objects.prefetch_related('products'), many=True, required=False
    )
    # For a product, replaces the calculated price; for a custom item, its price.
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, required=False)

    colors = pick_list('colors')
    damages = pick_list('damages')
    stains = pick_list('stains')
    materials = pick_list('materials')
    patterns = pick_list('patterns')
    styles = pick_list('styles')
    brand = serializers.CharField(max_length=60, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    barcode = serializers.CharField(max_length=40, required=False, allow_blank=True)

    def validate(self, attrs):
        product = attrs.get('product')
        if product is None:
            missing = {f: 'Required for a custom item.' for f in ('name', 'price') if f not in attrs}
            if missing:
                raise serializers.ValidationError(missing)
            if attrs.get('weight') is not None:
                raise serializers.ValidationError({'weight': 'Custom items are priced per item.'})
        else:
            if not product.active:
                raise serializers.ValidationError({'product': f'{product.name} is not active.'})
            by_weight = product.pricing_unit == Product.PricingUnit.WEIGHT
            if by_weight and attrs.get('weight') is None:
                raise serializers.ValidationError({'weight': f'{product.name} is priced by weight.'})
            if not by_weight and attrs.get('weight') is not None:
                raise serializers.ValidationError({'weight': f'{product.name} is priced per item.'})
        for upcharge in attrs.get('upcharges', []):
            offered = upcharge.products.all()
            if not upcharge.active or (offered and product not in offered):
                raise serializers.ValidationError({'upcharges': f'{upcharge.name} is not offered on this item.'})
        return attrs

    def to_new_item(self, attrs):
        details = {f: attrs[f] for f in ('colors', 'damages', 'stains', 'materials', 'patterns', 'styles',
                                          'brand', 'notes', 'barcode') if f in attrs}
        return NewItem(
            product=attrs.get('product'), name=attrs.get('name', ''), section=attrs.get('section'),
            weight=attrs.get('weight'), upcharges=attrs.get('upcharges', []), price=attrs.get('price'),
            details=details,
        )


class NewOrderSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=Order.Type.choices, default=Order.Type.IN_STORE)
    # Retail sales may leave it out to use the store's walk-in "Retail customer".
    customer = CompanyScopedPrimaryKeyField(
        queryset=Customer.objects.select_related('business__price_list', 'price_list'), required=False, allow_null=True
    )
    # Blank means the customer's usual price list.
    price_list = CompanyScopedPrimaryKeyField(queryset=PriceList.objects.all(), required=False, allow_null=True)
    express = serializers.BooleanField(default=False)
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    # Blank means the store's turnaround rules decide. Ignored for retail sales.
    due_at = serializers.DateTimeField(required=False)
    # Bags taken in, for Quick Drop.
    bags = serializers.IntegerField(min_value=0, required=False, default=0)
    # Leave empty for Quick Drop; its items are added in Detailing.
    items = NewItemSerializer(many=True, required=False, default=list)


class DetailOrderSerializer(serializers.Serializer):
    # Replaces the order's items. Leave out to keep the items it already has.
    items = NewItemSerializer(many=True, required=False)


class EditItemsSerializer(serializers.Serializer):
    # The order's full list of items; replaces the current ones.
    items = NewItemSerializer(many=True, allow_empty=False)
    # Leave out to keep the order's current setting.
    express = serializers.BooleanField(required=False)


class WeightsField(serializers.DictField):
    """New weights for weight-priced items: {"<item id>": "<weight>"}."""

    def __init__(self, **kwargs):
        super().__init__(
            child=serializers.DecimalField(max_digits=8, decimal_places=2, min_value=Decimal('0.01')),
            required=False, **kwargs,
        )

    def to_internal_value(self, data):
        weights = super().to_internal_value(data)
        try:
            return {int(item_id): weight for item_id, weight in weights.items()}
        except ValueError:
            raise serializers.ValidationError('Use item IDs as keys.')


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = [
            'id', 'product', 'section', 'name', 'weight', 'pieces', 'unit_price', 'upcharges', 'price',
            'price_overridden', 'colors', 'damages', 'stains', 'materials', 'patterns', 'styles', 'brand',
            'notes', 'barcode',
        ]
        read_only_fields = fields


class OrderEventSerializer(serializers.ModelSerializer):
    label = serializers.CharField(source='get_kind_display', read_only=True)
    user = serializers.StringRelatedField()

    class Meta:
        model = OrderEvent
        fields = ['kind', 'label', 'detail', 'user', 'created_at']


class OrderIssueSerializer(serializers.ModelSerializer):
    order_number = serializers.IntegerField(source='order.number', read_only=True)
    customer = serializers.CharField(source='order.customer.full_name', read_only=True)
    order_due_at = serializers.DateTimeField(source='order.due_at', read_only=True)
    reported_by = serializers.StringRelatedField()
    solved_by = serializers.StringRelatedField()
    solved = serializers.BooleanField(read_only=True)

    class Meta:
        model = OrderIssue
        fields = [
            'id', 'order', 'order_number', 'customer', 'order_due_at', 'stage', 'text',
            'reported_by', 'reported_at', 'solved', 'solved_by', 'solved_at', 'resolution',
        ]
        read_only_fields = ['order', 'stage', 'reported_at', 'solved_at', 'resolution']


class NewIssueSerializer(serializers.Serializer):
    text = serializers.CharField()


class NewIssueForOrderSerializer(NewIssueSerializer):
    """An issue raised from the Issues tab, which picks the order."""

    order = StoreScopedPrimaryKeyField(queryset=Order.objects.filter(deleted_at__isnull=True))


class SolveIssueSerializer(serializers.Serializer):
    # How the issue was resolved.
    resolution = serializers.CharField()


class OrderPhotoSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.StringRelatedField()

    class Meta:
        model = OrderPhoto
        fields = ['id', 'item', 'image', 'caption', 'uploaded_by', 'uploaded_at']
        read_only_fields = ['uploaded_at']

    def validate_item(self, item):
        if item is not None and item.order_id != self.context['order'].pk:
            raise serializers.ValidationError('That item is not on this order.')
        return item


class DeleteOrderSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')


class OrderCustomerSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Customer
        fields = ['id', 'full_name', 'phone']


class OrderListSerializer(serializers.ModelSerializer):
    """A row on the order board."""

    customer = OrderCustomerSerializer(read_only=True)
    pieces = serializers.IntegerField(read_only=True)
    open_issues = serializers.IntegerField(read_only=True)
    # e.g. "Suit ×2, Shirt"
    summary = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'number', 'customer', 'type', 'status', 'express', 'summary', 'notes', 'due_at',
            'pieces', 'bags', 'hanging', 'rack', 'total', 'open_issues', 'created_at',
        ]
        read_only_fields = fields

    def get_summary(self, order) -> str:
        return order_summary(order)


class OrderSerializer(serializers.ModelSerializer):
    """Order detail. Only notes, due date, rack, bags and hanging can be changed directly."""

    customer = OrderCustomerSerializer(read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)
    issues = OrderIssueSerializer(many=True, read_only=True)
    photos = OrderPhotoSerializer(many=True, read_only=True)
    events = OrderEventSerializer(many=True, read_only=True)
    created_by = serializers.StringRelatedField()

    class Meta:
        model = Order
        fields = [
            'id', 'number', 'customer', 'type', 'status', 'express', 'notes', 'due_at',
            'price_list', 'discount_percent', 'subtotal', 'minimum_charge', 'discount', 'taxes', 'tax', 'total',
            'rack', 'bags', 'hanging', 'items', 'issues', 'photos', 'events',
            'created_by', 'created_at', 'detailed_at', 'cleaned_at', 'collected_at',
        ]
        read_only_fields = [
            'number', 'type', 'status', 'express', 'price_list', 'discount_percent', 'subtotal',
            'minimum_charge', 'discount', 'taxes', 'tax', 'total', 'created_at', 'detailed_at', 'cleaned_at', 'collected_at',
        ]


class MarkCleanedSerializer(serializers.Serializer):
    # Required when the store prompts for the rack location (the default).
    rack = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')
    # Required when the store prompts for bags and hanging items.
    bags = serializers.IntegerField(min_value=0, required=False)
    hanging = serializers.IntegerField(min_value=0, required=False)
    # Required for every weight-priced item when the store prompts to re-weigh.
    weights = WeightsField()


class MarkCollectedSerializer(serializers.Serializer):
    # Required for every weight-priced item when the store prompts to re-weigh at collection.
    weights = WeightsField()


class OrderRevisionSerializer(serializers.ModelSerializer):
    """A row in the order edits log."""

    order_id = serializers.IntegerField(source='order.pk', read_only=True)
    order_number = serializers.IntegerField(source='order.number', read_only=True)
    customer = serializers.CharField(source='order.customer.full_name', read_only=True)
    edited_by = serializers.StringRelatedField()

    class Meta:
        model = OrderRevision
        fields = [
            'id', 'order_id', 'order_number', 'customer', 'created', 'summary', 'status', 'total', 'discount',
            'price_list', 'due_at', 'changes', 'edited_by', 'edited_at',
        ]
        read_only_fields = fields


class DeletedOrderSerializer(serializers.ModelSerializer):
    """A row in the order deletions log."""

    customer = serializers.CharField(source='customer.full_name', read_only=True)
    summary = serializers.SerializerMethodField()
    deleted_by = serializers.StringRelatedField()

    class Meta:
        model = Order
        fields = [
            'id', 'number', 'customer', 'summary', 'notes', 'total', 'status', 'deleted_by', 'deleted_at',
            'deletion_reason',
        ]
        read_only_fields = fields

    def get_summary(self, order) -> str:
        return order_summary(order)


class CustomerOverviewSerializer(serializers.Serializer):
    total_orders = serializers.IntegerField()
    lifetime_value = serializers.DecimalField(max_digits=12, decimal_places=2)
    average_order = serializers.DecimalField(max_digits=10, decimal_places=2)
    active_orders = OrderListSerializer(many=True)
