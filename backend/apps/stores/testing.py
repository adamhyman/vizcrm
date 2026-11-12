"""Test helpers for creating stores and staff."""

from apps.accounts.models import User

from .models import Company, Store


def create_store(name='Main St', company=None, **fields):
    """A store, in a new company of the same name unless `company` is given."""
    company = company or Company.objects.create(name=name)
    return Store.objects.create(company=company, name=name, **fields)


def create_staff(username, *stores, **fields):
    """A staff member of the stores' company, allowed at `stores`."""
    user = User.objects.create_user(username, password='pw', company=stores[0].company, **fields)
    user.stores.add(*stores)
    return user
