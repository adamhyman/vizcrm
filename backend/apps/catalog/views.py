from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.stores.scoping import CompanyScopedViewSet, StoreScopedViewSet

from .models import PriceList, PriceListItem, Product, Section, StoreProduct, Upcharge
from .serializers import (
    BulkUpdateSerializer,
    PriceListItemSerializer,
    PriceListSerializer,
    ProductSerializer,
    SectionSerializer,
    StoreProductSerializer,
    UpchargeSerializer,
)
from .services import BulkUpdateError, bulk_update_products, price_list_overrides, store_settings


class SectionViewSet(CompanyScopedViewSet):
    queryset = Section.objects.all()
    serializer_class = SectionSerializer

    def destroy(self, request, *args, **kwargs):
        section = self.get_object()
        if section.products.exists():
            return Response(
                {'detail': 'Move or delete this section\'s products first, or mark it inactive.'},
                status=status.HTTP_409_CONFLICT,
            )
        return super().destroy(request, *args, **kwargs)


@extend_schema_view(list=extend_schema(parameters=[
    OpenApiParameter('section', int),
    OpenApiParameter('active', bool),
    OpenApiParameter('search', str, description='Part of the product name.'),
    OpenApiParameter('price_list', int, description='Effective prices for this price list; leaves out '
                     'products not offered on it.'),
    OpenApiParameter('available_here', bool, description='Only products the current store sells (true) '
                     'or does not sell (false).'),
]))
class ProductViewSet(CompanyScopedViewSet):
    """The company's products, with prices and availability at the current store.

    Pass ?price_list=<id> to get effective prices for that list.
    Filters: ?section=<id>, ?active=true|false, ?search=<text>, ?available_here=true|false.
    """

    queryset = Product.objects.select_related('section__company').prefetch_related('price_lists')
    serializer_class = ProductSerializer
    company_lookup = 'section__company'

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if section := params.get('section'):
            qs = qs.filter(section_id=section)
        if (active := params.get('active')) in ('true', 'false'):
            qs = qs.filter(active=active == 'true')
        if search := params.get('search'):
            qs = qs.filter(name__icontains=search)
        if (available := params.get('available_here')) in ('true', 'false'):
            hidden = StoreProduct.objects.filter(store=self.request.store, available=False).values('product')
            qs = qs.exclude(pk__in=hidden) if available == 'true' else qs.filter(pk__in=hidden)
        if (price_list_id := params.get('price_list')) and self.action == 'list':
            price_list = PriceList.objects.filter(pk=price_list_id, company=self.request.company).first()
            # The default list offers every product.
            if price_list and not price_list.is_default:
                qs = qs.filter(Q(price_lists=None) | Q(price_lists=price_list)).distinct()
        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if hasattr(self.request, 'store'):
            context['store_settings'] = store_settings(self.request.store)
        if price_list_id := self.request.query_params.get('price_list'):
            price_list = get_object_or_404(
                PriceList.objects.prefetch_related('items'), pk=price_list_id, company=self.request.company
            )
            context['price_overrides'] = price_list_overrides(price_list)
        return context

    @action(detail=False, methods=['post'], url_path='bulk-update')
    def bulk_update(self, request):
        """Preview (apply=false) or apply a bulk change; returns the old → new values."""
        serializer = BulkUpdateSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            changes = bulk_update_products(
                data['products'], data['changes'], store=request.store,
                price_list=data.get('price_list'), apply=data['apply']
            )
        except BulkUpdateError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'applied': data['apply'],
            'product_count': len({c['product_id'] for c in changes}),
            'changes': changes,
        })


class PriceListViewSet(CompanyScopedViewSet):
    queryset = PriceList.objects.all()
    serializer_class = PriceListSerializer

    def destroy(self, request, *args, **kwargs):
        if self.get_object().is_default:
            return Response(
                {'detail': 'The default price list cannot be deleted.'}, status=status.HTTP_409_CONFLICT
            )
        return super().destroy(request, *args, **kwargs)


@extend_schema_view(list=extend_schema(parameters=[OpenApiParameter('price_list', int)]))
class PriceListItemViewSet(CompanyScopedViewSet):
    """Price overrides. Filter with ?price_list=<id>."""

    queryset = PriceListItem.objects.select_related('product')
    serializer_class = PriceListItemSerializer
    company_lookup = 'price_list__company'

    def get_queryset(self):
        qs = super().get_queryset()
        if price_list := self.request.query_params.get('price_list'):
            qs = qs.filter(price_list_id=price_list)
        return qs


class UpchargeViewSet(CompanyScopedViewSet):
    queryset = Upcharge.objects.prefetch_related('products')
    serializer_class = UpchargeSerializer


@extend_schema_view(list=extend_schema(parameters=[OpenApiParameter('product', int)]))
class StoreProductViewSet(StoreScopedViewSet):
    """The current store's own product prices and products it doesn't sell. Filter with ?product=<id>.

    Blank prices fall back to the product's; price lists still win over these.
    """

    queryset = StoreProduct.objects.select_related('product')
    serializer_class = StoreProductSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if product := self.request.query_params.get('product'):
            qs = qs.filter(product_id=product)
        return qs
