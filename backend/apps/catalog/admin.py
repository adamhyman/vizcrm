from django.contrib import admin

from .models import PriceList, PriceListItem, Product, Section, Upcharge


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'store', 'position', 'active')
    list_filter = ('store', 'active')
    list_editable = ('position', 'active')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'section', 'pricing_unit', 'price', 'express_price', 'pieces_per_unit', 'active')
    list_filter = ('section__store', 'section', 'pricing_unit', 'active', 'available_online')
    list_editable = ('price', 'express_price', 'active')
    search_fields = ('name', 'sku')


class PriceListItemInline(admin.TabularInline):
    model = PriceListItem
    extra = 0
    autocomplete_fields = ('product',)


@admin.register(PriceList)
class PriceListAdmin(admin.ModelAdmin):
    list_display = ('name', 'store', 'is_default')
    inlines = [PriceListItemInline]


@admin.register(Upcharge)
class UpchargeAdmin(admin.ModelAdmin):
    list_display = ('name', 'store', 'kind', 'amount', 'active')
    filter_horizontal = ('products',)
