from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('sections', views.SectionViewSet)
router.register('products', views.ProductViewSet)
router.register('price-lists', views.PriceListViewSet)
router.register('price-list-items', views.PriceListItemViewSet)
router.register('upcharges', views.UpchargeViewSet)

urlpatterns = router.urls
