from django.contrib import admin

from .models import PriceList, PriceListItem, Product, Section, StoreProduct, Upcharge


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'position', 'retail', 'active')
    list_filter = ('company', 'active')
    list_editable = ('position', 'retail', 'active')


class StoreProductInline(admin.TabularInline):
    model = StoreProduct
    extra = 0
    verbose_name = 'store price / availability'
    verbose_name_plural = 'store prices / availability'


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'section', 'pricing_unit', 'price', 'express_price', 'pieces_per_unit', 'active')
    list_filter = ('section__company', 'section', 'pricing_unit', 'active', 'available_online')
    list_editable = ('price', 'express_price', 'active')
    search_fields = ('name', 'sku')
    filter_horizontal = ('price_lists',)
    inlines = [StoreProductInline]


class PriceListItemInline(admin.TabularInline):
    model = PriceListItem
    extra = 0
    autocomplete_fields = ('product',)


@admin.register(PriceList)
class PriceListAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'is_default')
    inlines = [PriceListItemInline]


@admin.register(Upcharge)
class UpchargeAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'kind', 'amount', 'active')
    filter_horizontal = ('products',)
