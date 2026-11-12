from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.stores import views as store_views

urlpatterns = [
    # No public website yet; send visitors to the back office.
    path('', RedirectView.as_view(url='/admin/', permanent=False)),
    path('admin/', admin.site.urls),
    path('api/auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/store/', include('apps.stores.urls')),
    path('api/company/', store_views.CurrentCompanyView.as_view(), name='current_company'),
    path('api/my-stores/', store_views.MyStoresView.as_view(), name='my_stores'),
    path('api/', include('apps.catalog.urls')),
    path('api/', include('apps.contacts.urls')),
    path('api/', include('apps.orders.urls')),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='docs'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
