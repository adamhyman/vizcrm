from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('orders', views.OrderViewSet)
router.register('order-issues', views.OrderIssueViewSet)
router.register('order-edits', views.OrderEditViewSet, basename='order-edit')
router.register('order-deletions', views.OrderDeletionViewSet, basename='order-deletion')

urlpatterns = [
    path('orders/garment-options/', views.GarmentOptionsView.as_view(), name='garment_options'),
    path('customers/<int:pk>/overview/', views.CustomerOverviewView.as_view(), name='customer_overview'),
    *router.urls,
]
