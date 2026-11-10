from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.stores.scoping import StoreScopedViewSet

from .models import PriceList, PriceListItem, Product, Section, Upcharge
from .serializers import (
    BulkUpdateSerializer,
    PriceListItemSerializer,
    PriceListSerializer,
    ProductSerializer,
    SectionSerializer,
    UpchargeSerializer,
)
from .services import BulkUpdateError, bulk_update_products, price_list_overrides


class SectionViewSet(StoreScopedViewSet):
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


class ProductViewSet(StoreScopedViewSet):
    """Products. Pass ?price_list=<id> to get effective prices for that list.

    Filters: ?section=<id>, ?active=true|false, ?search=<text>.
    """

    queryset = Product.objects.select_related('section__store')
    serializer_class = ProductSerializer
    store_lookup = 'section__store'

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if section := params.get('section'):
            qs = qs.filter(section_id=section)
        if (active := params.get('active')) in ('true', 'false'):
            qs = qs.filter(active=active == 'true')
        if search := params.get('search'):
            qs = qs.filter(name__icontains=search)
        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if price_list_id := self.request.query_params.get('price_list'):
            price_list = get_object_or_404(
                PriceList.objects.prefetch_related('items'), pk=price_list_id, store=self.request.user.store
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
                data['products'], data['changes'], price_list=data.get('price_list'), apply=data['apply']
            )
        except BulkUpdateError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'applied': data['apply'],
            'product_count': len({c['product_id'] for c in changes}),
            'changes': changes,
        })


class PriceListViewSet(StoreScopedViewSet):
    queryset = PriceList.objects.all()
    serializer_class = PriceListSerializer

    def destroy(self, request, *args, **kwargs):
        if self.get_object().is_default:
            return Response(
                {'detail': 'The default price list cannot be deleted.'}, status=status.HTTP_409_CONFLICT
            )
        return super().destroy(request, *args, **kwargs)


class PriceListItemViewSet(StoreScopedViewSet):
    """Price overrides. Filter with ?price_list=<id>."""

    queryset = PriceListItem.objects.select_related('product')
    serializer_class = PriceListItemSerializer
    store_lookup = 'price_list__store'

    def get_queryset(self):
        qs = super().get_queryset()
        if price_list := self.request.query_params.get('price_list'):
            qs = qs.filter(price_list_id=price_list)
        return qs


class UpchargeViewSet(StoreScopedViewSet):
    queryset = Upcharge.objects.prefetch_related('products')
    serializer_class = UpchargeSerializer
