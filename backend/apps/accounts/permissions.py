from rest_framework.permissions import BasePermission

from apps.stores.services import client_ip, ip_allowed

from .models import User


class IsStoreStaff(BasePermission):
    """Signed-in staff member attached to a store, connecting from an allowed IP."""

    message = 'Only store staff can do this.'

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.role != User.Role.STAFF:
            return False
        if not user.store_id:
            self.message = (
                'Your account is not attached to a store. Set its store in the admin, '
                'or run: manage.py seed_demo_catalog --user <username>'
            )
            return False
        if not user.is_superuser and not ip_allowed(user.store, client_ip(request)):
            self.message = 'This store only allows staff access from approved locations.'
            return False
        return True
