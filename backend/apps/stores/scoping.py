"""Helpers that restrict API access to the current store, or to its company.

`IsStoreStaff` sets `request.store` (the store the user is working at) and
`request.company` (its company) before any of these run.
"""

from rest_framework import serializers, viewsets

from apps.accounts.permissions import IsStoreStaff


class StoreScopedViewSet(viewsets.ModelViewSet):
    """Limits every query to the current store.

    Set `store_lookup` to the ORM path from the model to its Store. When it is the
    model's own `store` field, new objects are attached to the current store.
    """

    permission_classes = [IsStoreStaff]
    store_lookup = 'store'

    def get_queryset(self):
        return super().get_queryset().filter(**{self.store_lookup: self.request.store})

    def perform_create(self, serializer):
        if self.store_lookup == 'store':
            serializer.save(store=self.request.store)
        else:
            serializer.save()


class CompanyScopedViewSet(viewsets.ModelViewSet):
    """Limits every query to the current store's company (shared catalog, customers…).

    Set `company_lookup` to the ORM path from the model to its Company. When it is
    the model's own `company` field, new objects are attached to the company.
    """

    permission_classes = [IsStoreStaff]
    company_lookup = 'company'

    def get_queryset(self):
        return super().get_queryset().filter(**{self.company_lookup: self.request.company})

    def perform_create(self, serializer):
        if self.company_lookup == 'company':
            serializer.save(company=self.request.company)
        else:
            serializer.save()


class StoreScopedPrimaryKeyField(serializers.PrimaryKeyRelatedField):
    """Only accepts objects belonging to the current store."""

    def __init__(self, store_lookup='store', **kwargs):
        self.store_lookup = store_lookup
        super().__init__(**kwargs)

    def get_queryset(self):
        return super().get_queryset().filter(**{self.store_lookup: self.context['request'].store})


class CompanyScopedPrimaryKeyField(serializers.PrimaryKeyRelatedField):
    """Only accepts objects belonging to the current store's company."""

    def __init__(self, company_lookup='company', **kwargs):
        self.company_lookup = company_lookup
        super().__init__(**kwargs)

    def get_queryset(self):
        return super().get_queryset().filter(**{self.company_lookup: self.context['request'].company})
