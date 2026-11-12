from django.utils import timezone


class StoreTimezoneMiddleware:
    """Show and enter dates/times in the signed-in user's store timezone.

    Uses the store named in the X-Store header, else the first store the user may
    work at. Affects the admin and any template rendering; API responses already
    include explicit UTC offsets.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        store = self._store(request)
        if store is not None:
            timezone.activate(store.tz)
        else:
            timezone.deactivate()
        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()

    @staticmethod
    def _store(request):
        from apps.accounts.permissions import STORE_HEADER, allowed_stores

        user = getattr(request, 'user', None)
        if not (user and user.is_authenticated):
            return None
        stores = allowed_stores(user)
        if store_id := request.headers.get(STORE_HEADER):
            stores = stores.filter(pk=store_id) if store_id.isdigit() else stores.none()
        return stores.order_by('pk').first()
