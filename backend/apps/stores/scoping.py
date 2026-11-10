"""Helpers that restrict API access to the requesting user's store."""

from rest_framework import serializers, viewsets

from apps.accounts.permissions import IsStoreStaff


class StoreScopedViewSet(viewsets.ModelViewSet):
    """Limits every query to the requesting user's store.

    Set `store_lookup` to the ORM path from the model to its Store. When it is the
    model's own `store` field, new objects are attached to the user's store.
    """

    permission_classes = [IsStoreStaff]
    store_lookup = 'store'

    def get_queryset(self):
        return super().get_queryset().filter(**{self.store_lookup: self.request.user.store})

    def perform_create(self, serializer):
        if self.store_lookup == 'store':
            serializer.save(store=self.request.user.store)
        else:
            serializer.save()


class StoreScopedPrimaryKeyField(serializers.PrimaryKeyRelatedField):
    """Only accepts objects belonging to the requesting user's store."""

    def __init__(self, store_lookup='store', **kwargs):
        self.store_lookup = store_lookup
        super().__init__(**kwargs)

    def get_queryset(self):
        store = self.context['request'].user.store
        return super().get_queryset().filter(**{self.store_lookup: store})
