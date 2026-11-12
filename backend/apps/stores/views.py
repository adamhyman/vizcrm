from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsStoreStaff, allowed_stores

from .models import BusinessHours, ClosedDate, Shift, Station, TaxRate
from .scoping import StoreScopedViewSet
from .serializers import (
    BusinessHoursSerializer,
    ClosedDateSerializer,
    CompanySerializer,
    DueDateQuerySerializer,
    ShiftSerializer,
    StationSerializer,
    StoreChoiceSerializer,
    StoreSerializer,
    TaxRateSerializer,
)
from .services import due_at


class CurrentStoreView(generics.RetrieveUpdateAPIView):
    """Settings of the store the user is working at. Send the logo as multipart form data."""

    permission_classes = [IsStoreStaff]
    serializer_class = StoreSerializer

    def get_object(self):
        return self.request.store


class CurrentCompanyView(generics.RetrieveUpdateAPIView):
    """Settings shared by all of the company's stores."""

    permission_classes = [IsStoreStaff]
    serializer_class = CompanySerializer

    def get_object(self):
        return self.request.company


class MyStoresView(generics.ListAPIView):
    """Stores the signed-in user may work at; send one's ID in the X-Store header."""

    permission_classes = [IsAuthenticated]
    serializer_class = StoreChoiceSerializer
    pagination_class = None

    def get_queryset(self):
        return allowed_stores(self.request.user).order_by('name')


class DueDateView(APIView):
    """Preview the due date for an order: ?express=true&extra_days=1&dropped_off_at=<ISO time>."""

    permission_classes = [IsStoreStaff]

    @extend_schema(
        parameters=[DueDateQuerySerializer],
        responses=inline_serializer('DueDate', {'due_at': serializers.DateTimeField()}),
    )
    def get(self, request):
        query = DueDateQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data
        due = due_at(
            request.store,
            params.get('dropped_off_at') or timezone.now(),
            express=params['express'],
            extra_days=params['extra_days'],
        )
        return Response({'due_at': due.isoformat()})


class StationViewSet(StoreScopedViewSet):
    queryset = Station.objects.all()
    serializer_class = StationSerializer


class TaxRateViewSet(StoreScopedViewSet):
    queryset = TaxRate.objects.all()
    serializer_class = TaxRateSerializer


class BusinessHoursViewSet(StoreScopedViewSet):
    queryset = BusinessHours.objects.all()
    serializer_class = BusinessHoursSerializer


class ShiftViewSet(StoreScopedViewSet):
    queryset = Shift.objects.all()
    serializer_class = ShiftSerializer


class ClosedDateViewSet(StoreScopedViewSet):
    """Closed dates. Upcoming only by default; ?all=true includes past dates."""

    queryset = ClosedDate.objects.all()
    serializer_class = ClosedDateSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == 'list' and self.request.query_params.get('all') != 'true':
            qs = qs.filter(date__gte=timezone.localdate(timezone=self.request.store.tz))
        return qs
