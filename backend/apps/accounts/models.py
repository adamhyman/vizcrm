from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        STAFF = 'staff', 'Staff'
        DRIVER = 'driver', 'Driver'
        CUSTOMER = 'customer', 'Customer'

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STAFF)
    # The store a staff member or driver works at. Blank for customers and platform admins.
    store = models.ForeignKey(
        'stores.Store', on_delete=models.PROTECT, null=True, blank=True, related_name='users'
    )
