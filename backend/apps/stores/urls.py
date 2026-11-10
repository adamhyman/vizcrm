from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register('stations', views.StationViewSet)
router.register('tax-rates', views.TaxRateViewSet)
router.register('business-hours', views.BusinessHoursViewSet)
router.register('shifts', views.ShiftViewSet)
router.register('closed-dates', views.ClosedDateViewSet)

urlpatterns = [
    path('', views.CurrentStoreView.as_view(), name='current_store'),
    path('due-date/', views.DueDateView.as_view(), name='due_date'),
    *router.urls,
]
