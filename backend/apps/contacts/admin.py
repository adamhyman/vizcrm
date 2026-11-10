from django.contrib import admin

from .models import BusinessAccount, Customer, CustomerGroup


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone', 'email', 'city', 'business', 'store', 'created_at')
    list_filter = ('store', 'business', 'groups', 'marketing_opt_in')
    search_fields = ('first_name', 'last_name', 'phone_digits', 'email', 'street_address')
    autocomplete_fields = ('business',)
    filter_horizontal = ('groups',)
    fieldsets = (
        ('General', {'fields': (
            'store', ('first_name', 'last_name'), 'phone', 'email', 'notification_method', 'marketing_opt_in',
        )}),
        ('Address', {'fields': (
            'street_address', 'unit', ('city', 'region', 'postal_code'), ('latitude', 'longitude'),
            'driver_instructions',
        )}),
        ('Billing', {'fields': ('business', 'price_list', 'discount_percent', 'groups')}),
        ('Preferences & notes', {'fields': ('preferences', 'notes', 'private_notes')}),
    )


@admin.register(BusinessAccount)
class BusinessAccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_name', 'phone', 'store', 'active')
    list_filter = ('store', 'active')
    search_fields = ('name', 'contact_name')


@admin.register(CustomerGroup)
class CustomerGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'store')
    list_filter = ('store',)
