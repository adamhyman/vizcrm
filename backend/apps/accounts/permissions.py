from rest_framework.permissions import BasePermission

from apps.stores.services import client_ip, ip_allowed

from .models import User

# The store the user is working at, sent by the apps on every request.
STORE_HEADER = 'X-Store'


def allowed_stores(user):
    """Stores a staff member may work at. Superusers may use any store of their company."""
    if user.is_superuser and user.company_id:
        return user.company.stores.all()
    return user.stores.all()


class IsStoreStaff(BasePermission):
    """Signed-in staff member working at one of their stores, connecting from an allowed IP.

    The store comes from the X-Store header (a store ID); users allowed at only one
    store may leave it out. Sets `request.store` and `request.company`.
    """

    message = 'Only store staff can do this.'

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.role != User.Role.STAFF:
            return False
        stores = list(allowed_stores(user).select_related('company'))
        if not stores:
            self.message = (
                'Your account is not allowed at any store. Add stores to it in the admin, '
                'or run: manage.py seed_demo_catalog --user <username>'
            )
            return False
        store_id = request.headers.get(STORE_HEADER)
        if store_id:
            store = next((s for s in stores if str(s.pk) == store_id), None)
            if store is None:
                self.message = f'You are not allowed at store {store_id}.'
                return False
        elif len(stores) == 1:
            store = stores[0]
        else:
            self.message = f'Choose a store: send its ID in the {STORE_HEADER} header (see /api/my-stores/).'
            return False
        if not user.is_superuser and not ip_allowed(store, client_ip(request)):
            self.message = 'This store only allows staff access from approved locations.'
            return False
        request.store = store
        request.company = store.company
        return True
