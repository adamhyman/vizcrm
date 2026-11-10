from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class VizUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (('Store', {'fields': ('role', 'store')}),)
    list_display = ('username', 'email', 'role', 'store', 'is_staff')
