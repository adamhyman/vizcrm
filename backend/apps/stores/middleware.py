from django.utils import timezone


class StoreTimezoneMiddleware:
    """Show and enter dates/times in the signed-in user's store timezone.

    Affects the admin and any template rendering; API responses already include
    explicit UTC offsets.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        store = getattr(user, 'store', None) if user and user.is_authenticated else None
        if store is not None:
            timezone.activate(store.tz)
        else:
            timezone.deactivate()
        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()
