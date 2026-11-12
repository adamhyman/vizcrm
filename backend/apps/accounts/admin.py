from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class VizUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (('Company', {'fields': ('role', 'company', 'stores')}),)
    list_display = ('username', 'email', 'role', 'company', 'is_staff')
    list_filter = UserAdmin.list_filter + ('company', 'role')
    filter_horizontal = UserAdmin.filter_horizontal + ('stores',)
