from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction

from .models import PriceListItem, StoreProduct, money


@dataclass(frozen=True)
class UnitPrice:
    price: Decimal
    express_price: Decimal

    def for_order(self, express):
        return self.express_price if express else self.price


def price_list_overrides(price_list):
    """{product_id: PriceListItem} for a price list; empty for the default list or None."""
    if price_list is None or price_list.is_default:
        return {}
    return {item.product_id: item for item in price_list.items.all()}


def store_settings(store):
    """{product_id: StoreProduct} for a store's own prices and availability; empty for None."""
    if store is None:
        return {}
    return {s.product_id: s for s in StoreProduct.objects.filter(store=store)}


def unit_price(product, store, overrides=None, store_setting=None):
    """Effective per-unit prices for a product.

    A price-list override wins; otherwise the store's own price (`store_setting`, a
    StoreProduct) and then the product's. Each of price and express price falls back
    on its own, and express is price × the store's express multiplier when no
    explicit express price is set anywhere.
    """
    multiplier = store.express_multiplier
    item = (overrides or {}).get(product.pk)
    if item is not None:
        express = item.express_price if item.express_price is not None else money(item.price * multiplier)
        return UnitPrice(item.price, express)
    price, express = product.price, product.express_price
    if store_setting is not None:
        price = store_setting.price if store_setting.price is not None else price
        express = store_setting.express_price if store_setting.express_price is not None else express
    return UnitPrice(price, express if express is not None else money(price * multiplier))


# --- Bulk update -------------------------------------------------------------

MONEY_FIELDS = ('price', 'express_price', 'cost_price', 'minimum_price')
PRICE_LIST_FIELDS = ('price', 'express_price')
INT_FIELDS = ('extra_days',)
BOOL_FIELDS = ('active', 'available_online', 'request_item_details')

MONEY_OPS = ('set', 'increase_amount', 'decrease_amount', 'increase_percent', 'decrease_percent')


class BulkUpdateError(ValueError):
    pass


def _apply_money_op(old, op, value):
    old = old or Decimal('0')
    if op == 'set':
        new = value
    elif op == 'increase_amount':
        new = old + value
    elif op == 'decrease_amount':
        new = old - value
    elif op == 'increase_percent':
        new = old * (1 + value / 100)
    elif op == 'decrease_percent':
        new = old * (1 - value / 100)
    else:
        raise BulkUpdateError(f'Unknown operation {op!r}.')
    return max(money(new), Decimal('0.00'))


def _validate(changes, price_list):
    if not changes:
        raise BulkUpdateError('Choose at least one field to update.')
    allowed = PRICE_LIST_FIELDS if price_list and not price_list.is_default else (
        MONEY_FIELDS + INT_FIELDS + BOOL_FIELDS
    )
    for field, change in changes.items():
        if field not in allowed:
            raise BulkUpdateError(f'{field!r} cannot be bulk updated here.')
        if field in MONEY_FIELDS and change.get('op') not in MONEY_OPS:
            raise BulkUpdateError(f'{field!r} needs one of: {", ".join(MONEY_OPS)}.')


def _current_value(product, field, item, store):
    if item is not None:
        if field == 'express_price':
            return unit_price(product, store, {product.pk: item}).express_price
        return getattr(item, field)
    if field == 'express_price':
        return product.default_express_price(store)
    return getattr(product, field)


def bulk_update_products(products, changes, *, store, price_list=None, apply=False):
    """Preview (and optionally apply) a bulk change to many products.

    `changes` maps field name to a spec:
      money fields: {'op': one of MONEY_OPS, 'value': Decimal}
      extra_days:   {'value': int}
      active / available_online: {'value': bool}

    With a non-default `price_list`, only price and express price can change and
    the new values are written to that list (creating overrides as needed).

    Returns a list of {'product_id', 'product', 'field', 'old', 'new'} for every
    value that would change.
    """
    _validate(changes, price_list)
    use_list = price_list is not None and not price_list.is_default
    overrides = price_list_overrides(price_list) if use_list else {}

    planned = []  # (product, item_or_None, field, old, new)
    for product in products:
        item = overrides.get(product.pk)
        for field, change in changes.items():
            old = _current_value(product, field, item, store)
            if field in MONEY_FIELDS:
                new = _apply_money_op(old, change['op'], Decimal(str(change['value'])))
            elif field in INT_FIELDS:
                new = int(change['value'])
            else:
                new = bool(change['value'])
            if new != old:
                planned.append((product, item, field, old, new))

    if apply:
        _save(planned, price_list if use_list else None)

    return [
        {'product_id': p.pk, 'product': p.name, 'field': field, 'old': old, 'new': new}
        for p, _item, field, old, new in planned
    ]


@transaction.atomic
def _save(planned, price_list):
    touched = {}
    for product, item, field, _old, new in planned:
        if price_list is None:
            setattr(product, field, new)
            touched[('product', product.pk)] = product
            continue
        key = ('item', product.pk)
        target = touched.get(key) or item
        if target is None:
            target = PriceListItem(price_list=price_list, product=product, price=product.price)
        setattr(target, field, new)
        touched[key] = target
    for obj in touched.values():
        obj.full_clean()
        obj.save()
