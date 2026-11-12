import datetime

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.db.models import Count, Exists, IntegerField, OuterRef, Prefetch, Subquery, Sum
from django.db.models.functions import Coalesce
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsStoreStaff
from apps.contacts.models import Customer
from apps.stores.scoping import StoreScopedViewSet

from . import garments
from .models import Order, OrderEvent, OrderIssue, OrderItem, OrderPhoto, OrderRevision
from .serializers import (
    CustomerOverviewSerializer,
    DeletedOrderSerializer,
    DeleteOrderSerializer,
    DetailOrderSerializer,
    EditItemsSerializer,
    MarkCleanedSerializer,
    MarkCollectedSerializer,
    NewIssueForOrderSerializer,
    NewIssueSerializer,
    NewItemSerializer,
    NewOrderSerializer,
    OrderIssueSerializer,
    OrderListSerializer,
    OrderPhotoSerializer,
    OrderRevisionSerializer,
    OrderSerializer,
    SolveIssueSerializer,
)
from .services import (
    DUE_FILTERS,
    OrderError,
    add_photo,
    board_totals,
    create_order,
    customer_overview,
    delete_order,
    detail_order,
    edit_items,
    exclude_archived,
    filter_due,
    home_summary,
    mark_cleaned,
    mark_collected,
    record_revision,
    report_issue,
    search_orders,
    solve_issue,
)


class BoardPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


BOARD_FILTERS = [
    OpenApiParameter('status', str, enum=Order.Status.values),
    OpenApiParameter('section', int, description='Orders with at least one item in this section.'),
    OpenApiParameter('due', str, enum=DUE_FILTERS),
    OpenApiParameter('customer', int),
    OpenApiParameter('search', str, description='Order number, or customer phone / name / email.'),
    OpenApiParameter('include_archived', bool, description="Include orders past the store's archive settings."),
]

LOG_FILTERS = [
    OpenApiParameter('user', int, description='Who made the change.'),
    OpenApiParameter('since', datetime.date, description="From this day (store's timezone)."),
    OpenApiParameter('until', datetime.date, description="Up to and including this day (store's timezone)."),
    OpenApiParameter('search', str, description='Order number.'),
]

BoardTotals = inline_serializer('OrderBoardTotals', {
    'orders': serializers.IntegerField(),
    'pieces': serializers.IntegerField(),
    'bags': serializers.IntegerField(),
    'weight': serializers.DecimalField(max_digits=10, decimal_places=2),
})

HomeSummary = inline_serializer('OrderHomeSummary', {
    'detailing': BoardTotals,
    'cleaning': inline_serializer('OrderHomeCleaning', {when: BoardTotals for when in DUE_FILTERS}),
    'last_order': OrderListSerializer(allow_null=True),
})


def per_order(queryset, aggregate):
    """`aggregate` over the rows of `queryset` belonging to each order, as a subquery (0 if none)."""
    rows = queryset.filter(order=OuterRef('pk')).order_by().values('order').annotate(n=aggregate).values('n')
    return Coalesce(Subquery(rows), 0, output_field=IntegerField())


def board_rows(queryset):
    """Orders with what an order board row needs."""
    return queryset.select_related('customer').prefetch_related('items').annotate(
        pieces=per_order(OrderItem.objects.all(), Sum('pieces')),
        open_issues=per_order(OrderIssue.objects.filter(solved_at__isnull=True), Count('id')),
    )


def conflict(exc):
    return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)


def new_items(validated_items):
    return [NewItemSerializer().to_new_item(item) for item in validated_items]


def filter_log(queryset, request, user_field, time_field):
    """Filters shared by the order edits and deletions logs: ?user, ?since, ?until, ?search (order number)."""
    params = request.query_params
    tz = request.store.tz
    if user := params.get('user'):
        queryset = queryset.filter(**{user_field: user})
    for name, lookup, days in (('since', 'gte', 0), ('until', 'lt', 1)):
        try:
            day = datetime.date.fromisoformat(params.get(name, ''))
        except ValueError:
            continue
        start = datetime.datetime.combine(day + datetime.timedelta(days=days), datetime.time(), tzinfo=tz)
        queryset = queryset.filter(**{f'{time_field}__{lookup}': start})
    if (search := params.get('search', '').strip().lstrip('#')).isdigit():
        number_field = 'order__number' if queryset.model is OrderRevision else 'number'
        queryset = queryset.filter(**{number_field: int(search)})
    return queryset


@extend_schema_view(list=extend_schema(parameters=BOARD_FILTERS))
class OrderViewSet(StoreScopedViewSet):
    """Orders. Create with POST; move them along with detail, mark-cleaned and mark-collected.

    The list is the order board, newest first and paginated; `totals` gives the
    counts for the same filters. DELETE hides an order and adds it to the deletions log.
    """

    queryset = Order.objects.filter(deleted_at__isnull=True).select_related('customer', 'created_by')
    pagination_class = BoardPagination

    def get_serializer_class(self):
        if self.action == 'list':
            return OrderListSerializer
        if self.action == 'create':
            return NewOrderSerializer
        return OrderSerializer

    def filtered(self):
        qs = super().get_queryset()
        params = self.request.query_params
        store = self.request.store
        if (status_ := params.get('status')) in Order.Status.values:
            qs = qs.filter(status=status_)
        if section := params.get('section'):
            qs = qs.filter(Exists(OrderItem.objects.filter(order=OuterRef('pk'), section=section)))
        if (due := params.get('due')) in DUE_FILTERS:
            qs = filter_due(qs, store, due)
        if customer := params.get('customer'):
            qs = qs.filter(customer_id=customer)
        if search := params.get('search'):
            qs = search_orders(qs, store, search)
        if params.get('include_archived') != 'true':
            qs = exclude_archived(qs, store)
        return qs

    def get_queryset(self):
        if self.action == 'list':
            return board_rows(self.filtered())
        return super().get_queryset().prefetch_related(
            'items', Prefetch('issues', OrderIssue.objects.select_related('reported_by', 'solved_by')),
            Prefetch('events', OrderEvent.objects.select_related('user')),
            Prefetch('photos', OrderPhoto.objects.select_related('uploaded_by')),
        )

    @extend_schema(request=NewOrderSerializer, responses={201: OrderSerializer})
    def create(self, request, *args, **kwargs):
        serializer = NewOrderSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            order = create_order(
                request.store, request.user, data.get('customer'), new_items(data['items']),
                type=data['type'], express=data['express'], notes=data['notes'], due_at=data.get('due_at'),
                bags=data['bags'], price_list=data.get('price_list'),
            )
        except OrderError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(OrderSerializer(self.get_queryset().get(pk=order.pk)).data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def perform_update(self, serializer):
        changed = [
            Order._meta.get_field(name).verbose_name
            for name, value in serializer.validated_data.items()
            if getattr(serializer.instance, name) != value
        ]
        order = serializer.save()
        if changed:
            detail = ', '.join(changed).capitalize()
            OrderEvent.objects.create(order=order, kind=OrderEvent.Kind.EDITED, user=self.request.user, detail=detail)
            record_revision(order, self.request.user, changes=detail)

    @extend_schema(request=DeleteOrderSerializer)
    def destroy(self, request, *args, **kwargs):
        """Hide the order and add it to the deletions log. Send {"reason": "..."} to say why."""
        serializer = DeleteOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        delete_order(self.get_object(), request.user, reason=serializer.validated_data['reason'])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request={'multipart/form-data': OrderPhotoSerializer}, responses={201: OrderPhotoSerializer})
    @action(detail=True, methods=['post'])
    def photos(self, request, pk=None):
        """Attach a photo (multipart form data), optionally of one item on the order."""
        order = self.get_object()
        serializer = OrderPhotoSerializer(data=request.data, context={**self.get_serializer_context(), 'order': order})
        serializer.is_valid(raise_exception=True)
        photo = add_photo(order, request.user, **serializer.validated_data)
        return Response(OrderPhotoSerializer(photo, context=self.get_serializer_context()).data,
                        status=status.HTTP_201_CREATED)

    @extend_schema(responses=HomeSummary)
    @action(detail=False)
    def home(self, request):
        """The Home screen cards: Detailing totals, Cleaning overdue / today / tomorrow, and the last order."""
        orders = exclude_archived(super().get_queryset(), request.store)
        last = board_rows(orders).order_by('-created_at', '-id').first()
        return Response({
            **home_summary(orders, request.store),
            'last_order': OrderListSerializer(last).data if last else None,
        })

    @extend_schema(request=EditItemsSerializer, responses=OrderSerializer)
    @action(detail=True, methods=['post'], url_path='edit-items')
    def edit_items(self, request, pk=None):
        """Replace the order's items and reprice it. Not allowed once collected."""
        serializer = EditItemsSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            edit_items(self.get_object(), request.user, new_items(data['items']), express=data.get('express'))
        except OrderError as exc:
            return conflict(exc)
        return Response(OrderSerializer(self.get_object()).data)

    @extend_schema(parameters=BOARD_FILTERS, responses=BoardTotals)
    @action(detail=False)
    def totals(self, request):
        """Orders, pieces and weight for the board's current filters."""
        return Response(board_totals(self.filtered()))

    @extend_schema(request=DetailOrderSerializer, responses=OrderSerializer)
    # Not named `detail`: DRF uses that attribute on every viewset.
    @action(detail=True, methods=['post'], url_path='detail')
    def finish_detailing(self, request, pk=None):
        """Detailing → Cleaning, optionally setting the items (needed for Quick Drop orders)."""
        serializer = DetailOrderSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data.get('items')
        try:
            detail_order(self.get_object(), request.user, None if items is None else new_items(items))
        except OrderError as exc:
            return conflict(exc)
        return Response(OrderSerializer(self.get_object()).data)

    @extend_schema(request=MarkCleanedSerializer, responses=OrderSerializer)
    @action(detail=True, methods=['post'], url_path='mark-cleaned')
    def mark_cleaned(self, request, pk=None):
        """Cleaning → Ready, recording where it's racked, bags / hanging items and any new weights."""
        serializer = MarkCleanedSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            mark_cleaned(self.get_object(), request.user, **serializer.validated_data)
        except OrderError as exc:
            return conflict(exc)
        return Response(OrderSerializer(self.get_object()).data)

    @extend_schema(request=MarkCollectedSerializer, responses=OrderSerializer)
    @action(detail=True, methods=['post'], url_path='mark-collected')
    def mark_collected(self, request, pk=None):
        """Ready → Collected, with any new weights."""
        serializer = MarkCollectedSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            mark_collected(self.get_object(), request.user, **serializer.validated_data)
        except OrderError as exc:
            return conflict(exc)
        return Response(OrderSerializer(self.get_object()).data)

    @extend_schema(request=NewIssueSerializer, responses={201: OrderIssueSerializer})
    @action(detail=True, methods=['post'], url_path='report-issue')
    def report_issue(self, request, pk=None):
        serializer = NewIssueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        issue = report_issue(self.get_object(), request.user, serializer.validated_data['text'])
        return Response(OrderIssueSerializer(issue).data, status=status.HTTP_201_CREATED)


@extend_schema_view(list=extend_schema(parameters=[
    OpenApiParameter('solved', bool, description='Leave out to list all issues.'),
    OpenApiParameter('search', str, description='Order number, or customer phone / name / email.'),
]))
class OrderIssueViewSet(StoreScopedViewSet):
    """Issues across all orders (the board's Issues tab). Report one from the order."""

    queryset = OrderIssue.objects.filter(order__deleted_at__isnull=True).select_related(
        'order__customer', 'reported_by', 'solved_by'
    )
    serializer_class = OrderIssueSerializer
    store_lookup = 'order__store'
    pagination_class = BoardPagination
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if (solved := params.get('solved')) in ('true', 'false'):
            qs = qs.filter(solved_at__isnull=solved == 'false')
        if search := params.get('search'):
            orders = search_orders(Order.objects.filter(store=self.request.store), self.request.store, search)
            qs = qs.filter(order__in=orders)
        return qs

    @extend_schema(request=NewIssueForOrderSerializer, responses={201: OrderIssueSerializer})
    def create(self, request, *args, **kwargs):
        """Report an issue on any order (the Issues tab's New Issue)."""
        serializer = NewIssueForOrderSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        issue = report_issue(data['order'], request.user, data['text'])
        return Response(OrderIssueSerializer(issue).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=SolveIssueSerializer, responses=OrderIssueSerializer)
    @action(detail=True, methods=['post'], url_path='mark-solved')
    def mark_solved(self, request, pk=None):
        """Mark solved, with an explanation of how it was resolved."""
        serializer = SolveIssueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        issue = self.get_object()
        try:
            solve_issue(issue, request.user, serializer.validated_data['resolution'])
        except OrderError as exc:
            return conflict(exc)
        return Response(OrderIssueSerializer(issue).data)


@extend_schema_view(list=extend_schema(parameters=LOG_FILTERS))
class OrderEditViewSet(StoreScopedViewSet):
    """The order edits log: a snapshot of each order when it was created and after every edit."""

    queryset = OrderRevision.objects.select_related('order__customer', 'edited_by')
    serializer_class = OrderRevisionSerializer
    store_lookup = 'order__store'
    pagination_class = BoardPagination
    http_method_names = ['get', 'head', 'options']

    def get_queryset(self):
        return filter_log(super().get_queryset(), self.request, 'edited_by', 'edited_at')


@extend_schema_view(list=extend_schema(parameters=LOG_FILTERS))
class OrderDeletionViewSet(StoreScopedViewSet):
    """The order deletions log."""

    queryset = Order.objects.filter(deleted_at__isnull=False).select_related('customer', 'deleted_by').prefetch_related('items')
    serializer_class = DeletedOrderSerializer
    pagination_class = BoardPagination
    http_method_names = ['get', 'head', 'options']

    def get_queryset(self):
        return filter_log(super().get_queryset(), self.request, 'deleted_by', 'deleted_at').order_by('-deleted_at')


class CustomerOverviewView(APIView):
    """A customer's order totals and active orders, for their profile."""

    permission_classes = [IsStoreStaff]

    @extend_schema(responses=CustomerOverviewSerializer)
    def get(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk, company=request.company)
        overview = customer_overview(customer)
        overview['active_orders'] = board_rows(overview['active_orders'])
        return Response(CustomerOverviewSerializer(overview).data)


class GarmentOptionsView(APIView):
    """The pick lists for garment details at order entry."""

    permission_classes = [IsStoreStaff]

    @extend_schema(responses=inline_serializer('GarmentOptions', {
        'colors': serializers.ListField(child=inline_serializer('GarmentColor', {
            'name': serializers.CharField(), 'hex': serializers.CharField(),
        })),
        **{f: serializers.ListField(child=serializers.CharField())
           for f in ('damages', 'stains', 'materials', 'patterns', 'styles')},
        'max_choices': serializers.DictField(child=serializers.IntegerField()),
    }))
    def get(self, request):
        return Response({
            'colors': [{'name': name, 'hex': hex_} for name, hex_ in garments.COLORS],
            'damages': garments.DAMAGES,
            'stains': garments.STAINS,
            'materials': garments.MATERIALS,
            'patterns': garments.PATTERNS,
            'styles': garments.STYLES,
            'max_choices': garments.MAX_CHOICES,
        })
