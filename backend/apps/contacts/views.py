from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework.pagination import PageNumberPagination

from apps.stores.scoping import CompanyScopedViewSet

from .models import BusinessAccount, Customer, CustomerGroup
from .serializers import (
    BusinessAccountSerializer,
    CustomerGroupSerializer,
    CustomerSerializer,
)
from .services import search_customers


class CustomerPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


@extend_schema_view(list=extend_schema(parameters=[
    OpenApiParameter('search', str, description='Part of a phone number, or name / email words.'),
    OpenApiParameter('business', int),
    OpenApiParameter('group', int),
]))
class CustomerViewSet(CompanyScopedViewSet):
    """The company's customers, paginated. Filters: ?search=<name, phone or email>, ?business=<id>, ?group=<id>.

    New customers are shared by all the company's stores; `home_store` records where they were added.
    """

    queryset = Customer.objects.select_related('business__price_list', 'price_list').prefetch_related('groups')
    serializer_class = CustomerSerializer
    pagination_class = CustomerPagination

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if business := params.get('business'):
            qs = qs.filter(business_id=business)
        if group := params.get('group'):
            qs = qs.filter(groups=group)
        if search := params.get('search'):
            qs = search_customers(qs, search)
        return qs

    def perform_create(self, serializer):
        serializer.save(company=self.request.company, home_store=self.request.store)


@extend_schema_view(list=extend_schema(parameters=[OpenApiParameter('search', str, description='Name or phone.')]))
class BusinessAccountViewSet(CompanyScopedViewSet):
    """Business accounts. Filter with ?search=<name or phone>."""

    queryset = BusinessAccount.objects.all()
    serializer_class = BusinessAccountSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if search := self.request.query_params.get('search'):
            qs = qs.filter(Q(name__icontains=search) | Q(phone__icontains=search))
        return qs


class CustomerGroupViewSet(CompanyScopedViewSet):
    queryset = CustomerGroup.objects.all()
    serializer_class = CustomerGroupSerializer
