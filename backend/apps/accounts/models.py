from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        STAFF = 'staff', 'Staff'
        DRIVER = 'driver', 'Driver'
        CUSTOMER = 'customer', 'Customer'

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STAFF)
    # The company a staff member or driver works for, and the stores they may work at.
    # Blank for customers and platform admins.
    company = models.ForeignKey(
        'stores.Company', on_delete=models.PROTECT, null=True, blank=True, related_name='users'
    )
    stores = models.ManyToManyField('stores.Store', blank=True, related_name='staff')
