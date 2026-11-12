from django import forms
from django.contrib import admin

from apps.catalog.models import Product

from .models import Order, OrderEvent, OrderIssue, OrderItem, OrderPhoto
from .services import NewItem, OrderError, add_item, check_new_item


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ('name', 'weight', 'pieces', 'unit_price', 'price', 'price_overridden', 'colors', 'damages',
              'stains', 'notes', 'barcode')
    readonly_fields = ('name', 'weight', 'pieces', 'unit_price', 'price', 'price_overridden')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        # Items are added with NewOrderItemInline so they get priced.
        return False


class NewOrderItemForm(forms.ModelForm):
    """One item to add to an order: a product, or a custom item with a name and price."""

    name = forms.CharField(max_length=80, required=False, label='Custom item name',
                           help_text='Only for an item that is not a product.')
    price = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0, required=False,
                               help_text='Blank uses the calculated price. Required for a custom item.')

    class Meta:
        model = OrderItem
        fields = ('product', 'name', 'weight', 'price', 'notes', 'barcode')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Not the model's 0.00 default: a blank price means "calculate it".
        self.initial['price'] = None

    def clean(self):
        data = super().clean()
        product, weight = data.get('product'), data.get('weight')
        if product is None:
            for field in ('name', 'price'):
                if data.get(field) in (None, ''):
                    self.add_error(field, 'Required for a custom item.')
            if weight is not None:
                self.add_error('weight', 'Custom items are priced per item.')
        else:
            by_weight = product.pricing_unit == Product.PricingUnit.WEIGHT
            if not product.active:
                self.add_error('product', f'{product.name} is not active.')
            if by_weight and weight is None:
                self.add_error('weight', f'{product.name} is priced by weight.')
            if not by_weight and weight is not None:
                self.add_error('weight', f'{product.name} is priced per item.')
        if self.errors:
            return data
        self.new_item = NewItem(
            product=product, name=data.get('name', ''), weight=weight, price=data.get('price'),
            details={'notes': data.get('notes', ''), 'barcode': data.get('barcode', '')},
        )
        try:
            check_new_item(self.instance.order, self.new_item)
        except OrderError as exc:
            raise forms.ValidationError(str(exc))
        return data


class NewOrderItemInline(admin.TabularInline):
    """Adds items through the order service, so they are priced and the totals updated."""

    model = OrderItem
    form = NewOrderItemForm
    fields = ('product', 'name', 'weight', 'price', 'notes', 'barcode')
    extra = 1
    can_delete = False
    verbose_name = 'item to add'
    verbose_name_plural = 'Add items'

    def get_queryset(self, request):
        # Existing items are shown by OrderItemInline.
        return super().get_queryset(request).none()

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        products = formset.form.base_fields['product'].queryset
        formset.form.base_fields['product'].queryset = products.filter(
            section__company=obj.company_id if obj else None, active=True
        )
        return formset


class OrderIssueInline(admin.TabularInline):
    model = OrderIssue
    extra = 0
    fields = ('stage', 'text', 'reported_by', 'reported_at', 'solved_by', 'solved_at', 'resolution')
    readonly_fields = ('reported_at',)


class OrderPhotoInline(admin.TabularInline):
    model = OrderPhoto
    extra = 0
    fields = ('image', 'item', 'caption', 'uploaded_by', 'uploaded_at')
    readonly_fields = ('uploaded_at',)


class OrderEventInline(admin.TabularInline):
    model = OrderEvent
    extra = 0
    fields = ('created_at', 'kind', 'detail', 'user')
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('number', 'customer', 'status', 'express', 'due_at', 'rack', 'total', 'store', 'created_at')
    list_filter = ('store', 'status', 'type', 'express', ('deleted_at', admin.EmptyFieldListFilter))
    search_fields = ('number', 'customer__first_name', 'customer__last_name', 'customer__phone_digits')
    autocomplete_fields = ('customer',)
    readonly_fields = ('company', 'number', 'price_list', 'discount_percent', 'subtotal', 'minimum_charge', 'discount', 'taxes',
                       'tax', 'total', 'created_by', 'created_at', 'detailed_at', 'cleaned_at', 'collected_at',
                       'deleted_at', 'deleted_by', 'deletion_reason')
    fieldsets = (
        (None, {'fields': ('company', 'store', 'number', 'customer', 'type', 'status', 'express', 'due_at', 'notes')}),
        ('Pricing', {'fields': (
            'price_list', 'discount_percent', 'subtotal', 'minimum_charge', 'discount', 'taxes', 'tax', 'total',
        )}),
        ('Ready', {'fields': ('rack', 'bags', 'hanging')}),
        ('History', {'fields': (
            'created_by', 'created_at', 'detailed_at', 'cleaned_at', 'collected_at', 'deleted_at', 'deleted_by',
            'deletion_reason',
        )}),
    )
    inlines = [OrderItemInline, NewOrderItemInline, OrderIssueInline, OrderPhotoInline, OrderEventInline]

    def has_add_permission(self, request):
        # Orders are created through the POS / API so they get a number, prices and a timeline.
        return False

    def save_formset(self, request, form, formset, change):
        if not issubclass(formset.form, NewOrderItemForm):
            return super().save_formset(request, form, formset, change)
        formset.new_objects = [
            add_item(formset.instance, request.user, item_form.new_item)
            for item_form in formset.forms if item_form.has_changed()
        ]
        formset.changed_objects, formset.deleted_objects = [], []


@admin.register(OrderIssue)
class OrderIssueAdmin(admin.ModelAdmin):
    list_display = ('order', 'text', 'stage', 'reported_by', 'reported_at', 'solved_at')
    list_filter = ('order__store', 'stage')
