import datetime
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Max, Q, Sum
from django.utils import timezone

from apps.catalog.models import Product, Upcharge, money
from apps.catalog.services import price_list_overrides, store_settings, unit_price
from apps.contacts.models import Customer
from apps.contacts.services import search_customers
from apps.stores.models import Company, Store
from apps.stores.services import due_at as calculate_due_at

from .models import ZERO, Order, OrderEvent, OrderIssue, OrderItem, OrderPhoto, OrderRevision


class OrderError(ValueError):
    pass


@dataclass
class NewItem:
    """An item as entered at the POS. Either `product` or (`name` and `price`) for a custom item."""

    product: Product | None = None
    name: str = ''
    section: object = None
    weight: Decimal | None = None
    upcharges: list = field(default_factory=list)
    # Typed by staff; replaces the calculated price.
    price: Decimal | None = None
    details: dict = field(default_factory=dict)


# --- Pricing -----------------------------------------------------------------

def _base_price(product, unit, weight):
    base = money(unit * weight) if weight is not None else unit
    if product is not None and product.minimum_price is not None:
        base = max(base, product.minimum_price)
    return base


def _upcharge_amounts(upcharges, base):
    """Upcharge snapshots ({name, amount, percent}) with amounts worked out for `base`."""
    return [
        {**u, 'amount': str(money(base * Decimal(u['percent']) / 100) if u.get('percent') else u['amount'])}
        for u in upcharges
    ]


def _priced_item(new, overrides, express, settings, store):
    """An unsaved OrderItem with its price worked out from a NewItem.

    `settings` are the store's own product prices ({product_id: StoreProduct}).
    """
    product = new.product
    if product is None:
        unit = new.price
        pieces = 1
    else:
        unit = unit_price(product, store, overrides, settings.get(product.pk)).for_order(express)
        pieces = product.pieces_per_unit
    base = _base_price(product, unit, new.weight)
    upcharges = _upcharge_amounts([
        {'name': u.name, 'amount': str(u.amount), 'percent': str(u.amount) if u.kind == Upcharge.Kind.PERCENT else None}
        for u in new.upcharges
    ], base)
    calculated = base + sum((Decimal(u['amount']) for u in upcharges), ZERO)
    overridden = product is not None and new.price is not None
    return OrderItem(
        product=product,
        section=product.section if product else new.section,
        name=product.name if product else new.name,
        weight=new.weight,
        pieces=pieces,
        unit_price=unit,
        upcharges=upcharges,
        price=new.price if overridden else calculated,
        price_overridden=overridden,
        **new.details,
    )


def order_totals(store, item_prices, discount_percent, minimum=ZERO):
    """Subtotal, minimum charge, discount, per-rate taxes and total for a list of item prices.

    An order with items whose subtotal is under `minimum` is charged up to it.
    """
    subtotal = sum(item_prices, ZERO)
    minimum_charge = max(minimum - subtotal, ZERO) if item_prices else ZERO
    discount = money((subtotal + minimum_charge) * discount_percent / 100)
    net = subtotal + minimum_charge - discount
    rates = list(store.tax_rates.all())
    if store.tax_mode == Store.TaxMode.INCLUSIVE:
        # Prices already include tax; work out how much of the net is tax.
        divisor = 100 + sum((r.rate for r in rates), Decimal('0'))
        taxes = [(r, money(net * r.rate / divisor)) for r in rates]
        total = net
    else:
        taxes = [(r, money(net * r.rate / 100)) for r in rates]
        total = net + sum((amount for _, amount in taxes), ZERO)
    return {
        'subtotal': subtotal,
        'minimum_charge': minimum_charge,
        'discount': discount,
        'taxes': [{'name': r.name, 'rate': str(r.rate), 'amount': str(amount)} for r, amount in taxes],
        'tax': sum((amount for _, amount in taxes), ZERO),
        'total': total,
    }


# --- Lifecycle -------------------------------------------------------------------

def _goes_to_detailing(store, type_, new_items):
    if not store.detailing_enabled:
        return False
    if type_ == Order.Type.QUICK_DROP:
        return True
    if store.detailing_orders != Store.DetailingOrders.ALL:
        return False
    limit = {section.pk for section in store.detailing_sections.all()}
    if not limit:
        return True
    sections = {(new.product.section_id if new.product else getattr(new.section, 'pk', None)) for new in new_items}
    return bool(sections & limit)


def _check_items_for_type(store, type_, new_items):
    if type_ == Order.Type.QUICK_DROP:
        if not store.quick_drop_enabled:
            raise OrderError('Quick Drop is turned off for this store.')
        if new_items:
            raise OrderError('Quick Drop orders are itemised in Detailing; send no items.')
        return
    if not new_items:
        raise OrderError('Add at least one item.')
    if type_ == Order.Type.RETAIL:
        for new in new_items:
            section = new.product.section if new.product else new.section
            if section is not None and not section.retail:
                raise OrderError(f'{new.product or new.name} is not a retail item.')


def _minimum_for(order):
    store = order.store
    if order.type == Order.Type.RETAIL:
        return ZERO
    if order.express and store.minimum_express_order_amount:
        return store.minimum_express_order_amount
    return store.minimum_order_amount


def _discount_for(store, customer, type_):
    """The customer's discount, or the store's first-order discount if this is their first order and it's bigger."""
    percent = customer.discount_percent
    if type_ == Order.Type.RETAIL or customer.walk_in or store.first_order_discount_percent <= percent:
        return percent
    earlier = customer.orders.filter(deleted_at__isnull=True).exclude(type=Order.Type.RETAIL)
    return percent if earlier.exists() else store.first_order_discount_percent


def _set_totals(order, items):
    totals = order_totals(order.store, [i.price for i in items], order.discount_percent, _minimum_for(order))
    for name, value in totals.items():
        setattr(order, name, value)


def _check_sellable(order, new, settings):
    """Refuse a product that isn't on the order's price list or isn't sold at its store."""
    if new.product is None:
        return
    if not new.product.offered_on(order.price_list):
        raise OrderError(f'{new.product.name} is not offered on the {order.price_list.name} price list.')
    if (setting := settings.get(new.product.pk)) is not None and not setting.available:
        raise OrderError(f'{new.product.name} is not sold at {order.store.name}.')


def _save_items(order, new_items):
    """Price `new_items` with the order's store, price list, express and discount; replace its items and totals."""
    settings = store_settings(order.store)
    for new in new_items:
        _check_sellable(order, new, settings)
    overrides = price_list_overrides(order.price_list)
    items = [_priced_item(new, overrides, order.express, settings, order.store) for new in new_items]
    for item in items:
        item.order = order
    order.items.all().delete()
    OrderItem.objects.bulk_create(items)
    _set_totals(order, items)


def order_summary(order):
    """e.g. "Suit ×2, Shirt", or "2 bags" for a Quick Drop not yet itemised."""
    counts = {}
    for item in order.items.all():
        counts[item.name] = counts.get(item.name, 0) + 1
    if not counts:
        return f'{order.bags} bag' + ('' if order.bags == 1 else 's')
    return ', '.join(name if n == 1 else f'{name} ×{n}' for name, n in counts.items())


def record_revision(order, user, changes='', created=False):
    return OrderRevision.objects.create(
        order=order, created=created, summary=order_summary(order)[:200], status=order.status, total=order.total,
        discount=order.discount, price_list=order.price_list.name if order.price_list else '', due_at=order.due_at,
        changes=changes[:200], edited_by=user,
    )


def _check_editable(order):
    if order.deleted_at is not None:
        raise OrderError('This order has been deleted.')
    if order.status == Order.Status.COLLECTED:
        raise OrderError('Collected orders can no longer be changed.')


@transaction.atomic
def create_order(store, user, customer, new_items, type=Order.Type.IN_STORE, express=False, notes='',
                 due_at=None, bags=0, price_list=None):
    """Create an order. Retail sales may leave out the customer to use the store's walk-in customer.

    `price_list` overrides the customer's usual one for this order.
    """
    _check_items_for_type(store, type, new_items)
    now = timezone.now()
    if customer is None:
        if type != Order.Type.RETAIL:
            raise OrderError('Choose a customer.')
        customer = Customer.walk_in_for(store.company)
    if type == Order.Type.RETAIL:
        express, status, due_at = False, Order.Status.COLLECTED, now
    else:
        status = Order.Status.DETAILING if _goes_to_detailing(store, type, new_items) else Order.Status.CLEANING
    if due_at is None:
        extra_days = max((new.product.extra_days for new in new_items if new.product), default=0)
        due_at = calculate_due_at(store, now, express=express, extra_days=extra_days)

    # Lock the company row so two tills (in any of its stores) can't take the same order number.
    company = Company.objects.select_for_update().get(pk=store.company_id)
    number = (company.orders.aggregate(n=Max('number'))['n'] or 0) + 1
    order = Order(
        store=store, company=company, number=number, customer=customer, type=type, status=status, express=express, notes=notes,
        due_at=due_at, bags=bags, price_list=price_list or customer.effective_price_list(store),
        discount_percent=_discount_for(store, customer, type), created_by=user,
        collected_at=now if status == Order.Status.COLLECTED else None,
    )
    order.save()
    _save_items(order, new_items)
    order.save()
    OrderEvent.objects.create(order=order, kind=OrderEvent.Kind.CREATED, user=user)
    if status == Order.Status.COLLECTED:
        OrderEvent.objects.create(order=order, kind=OrderEvent.Kind.COLLECTED, user=user)
    record_revision(order, user, created=True)
    return order


def check_new_item(order, new):
    """Raise OrderError if `new` can't be added to `order`."""
    _check_editable(order)
    if order.type == Order.Type.RETAIL:
        _check_items_for_type(order.store, order.type, [new])
    _check_sellable(order, new, store_settings(order.store))


@transaction.atomic
def add_item(order, user, new):
    """Add one item to an order, priced with its store, price list, express and discount."""
    check_new_item(order, new)
    item = _priced_item(
        new, price_list_overrides(order.price_list), order.express, store_settings(order.store), order.store
    )
    item.order = order
    item.save()
    old_total = order.total
    _set_totals(order, list(order.items.all()))
    order.save()
    OrderEvent.objects.create(order=order, kind=OrderEvent.Kind.EDITED, user=user,
                              detail=f'Added {item.name}; total {old_total} → {order.total}')
    record_revision(order, user, changes='Items')
    return item


@transaction.atomic
def edit_items(order, user, new_items, express=None):
    """Replace an order's items (and optionally switch express), repricing it with its price list and discount."""
    _check_editable(order)
    if not new_items:
        raise OrderError('Add at least one item.')
    if order.type == Order.Type.RETAIL:
        _check_items_for_type(order.store, order.type, new_items)
    old_total = order.total
    if express is not None:
        order.express = express
    _save_items(order, new_items)
    order.save()
    OrderEvent.objects.create(order=order, kind=OrderEvent.Kind.EDITED, user=user,
                              detail=f'Items changed; total {old_total} → {order.total}')
    record_revision(order, user, changes='Items')
    return order


@transaction.atomic
def delete_order(order, user, reason=''):
    if order.deleted_at is not None:
        raise OrderError('This order has already been deleted.')
    order.deleted_at = timezone.now()
    order.deleted_by = user
    order.deletion_reason = reason
    order.save(update_fields=['deleted_at', 'deleted_by', 'deletion_reason'])
    OrderEvent.objects.create(order=order, kind=OrderEvent.Kind.DELETED, user=user, detail=reason)
    return order


@transaction.atomic
def detail_order(order, user, new_items=None):
    """Detailing → Cleaning. `new_items`, if given, replace the order's items (and reprice it)."""
    if order.status != Order.Status.DETAILING:
        raise OrderError(f'Only orders in Detailing can be detailed; this one is {order.get_status_display()}.')
    if new_items is not None:
        if not new_items:
            raise OrderError('Add at least one item.')
        _save_items(order, new_items)
        record_revision(order, user, changes='Items (detailing)')
    elif not order.items.exists():
        raise OrderError('Add the items before finishing detailing.')
    order.status = Order.Status.CLEANING
    order.detailed_at = timezone.now()
    order.save()
    pieces = order.items.aggregate(n=Sum('pieces'))['n']
    OrderEvent.objects.create(order=order, kind=OrderEvent.Kind.DETAILED, user=user,
                              detail=f'{pieces} piece' + ('' if pieces == 1 else 's'))
    return order


def _reweigh(order, user, weights, required):
    """Apply new weights ({item id: weight}) to weight-priced items and reprice the order.

    With `required`, every weight-priced item must be given a new weight.
    """
    weights = weights or {}
    items = list(order.items.all())
    weighed = {item.pk: item for item in items if item.weight is not None}
    unknown = set(weights) - set(weighed)
    if unknown:
        raise OrderError(f'Only weight-priced items on this order can be re-weighed (not item {min(unknown)}).')
    if required and set(weighed) - set(weights):
        missing = ', '.join(weighed[pk].name for pk in sorted(set(weighed) - set(weights)))
        raise OrderError(f'Re-weigh before continuing: {missing}.')
    changes = []
    for pk, weight in weights.items():
        item = weighed[pk]
        if weight == item.weight:
            continue
        changes.append(f'{item.name} {item.weight} → {weight}')
        item.weight = weight
        if not item.price_overridden:
            base = _base_price(item.product, item.unit_price, weight)
            item.upcharges = _upcharge_amounts(item.upcharges, base)
            item.price = base + sum((Decimal(u['amount']) for u in item.upcharges), ZERO)
        item.save(update_fields=['weight', 'upcharges', 'price'])
    if changes:
        _set_totals(order, items)
        order.save()
        OrderEvent.objects.create(order=order, kind=OrderEvent.Kind.EDITED, user=user,
                                  detail='Re-weighed: ' + '; '.join(changes))
        record_revision(order, user, changes='Weights')


@transaction.atomic
def mark_cleaned(order, user, rack='', bags=None, hanging=None, weights=None):
    """Cleaning → Ready. The store's settings decide whether rack, bags / hanging and new weights are required."""
    if order.status != Order.Status.CLEANING:
        raise OrderError(f'Only orders in Cleaning can be marked cleaned; this one is {order.get_status_display()}.')
    store = order.store
    if store.require_rack_when_cleaned and not rack:
        raise OrderError('Enter the rack location.')
    if store.require_bags_when_cleaned and (bags is None or hanging is None):
        raise OrderError('Enter the number of bags and hanging items.')
    _reweigh(order, user, weights, required=store.reweigh_when_cleaned)
    order.status = Order.Status.READY
    order.rack = rack
    order.bags = order.bags if bags is None else bags
    order.hanging = order.hanging if hanging is None else hanging
    order.cleaned_at = timezone.now()
    order.save(update_fields=['status', 'rack', 'bags', 'hanging', 'cleaned_at'])
    OrderEvent.objects.create(order=order, kind=OrderEvent.Kind.CLEANED, user=user,
                              detail=f'Rack {rack}' if rack else '')
    return order


@transaction.atomic
def mark_collected(order, user, weights=None):
    if order.status != Order.Status.READY:
        raise OrderError(f'Only Ready orders can be collected; this one is {order.get_status_display()}.')
    _reweigh(order, user, weights, required=order.store.reweigh_when_collected)
    order.status = Order.Status.COLLECTED
    order.collected_at = timezone.now()
    order.save(update_fields=['status', 'collected_at'])
    OrderEvent.objects.create(order=order, kind=OrderEvent.Kind.COLLECTED, user=user)
    return order


@transaction.atomic
def report_issue(order, user, text):
    issue = OrderIssue.objects.create(order=order, stage=order.status, text=text, reported_by=user)
    OrderEvent.objects.create(order=order, kind=OrderEvent.Kind.ISSUE_REPORTED, user=user, detail=text)
    return issue


@transaction.atomic
def solve_issue(issue, user, resolution):
    if issue.solved:
        raise OrderError('This issue is already solved.')
    issue.solved_by = user
    issue.solved_at = timezone.now()
    issue.resolution = resolution
    issue.save(update_fields=['solved_by', 'solved_at', 'resolution'])
    OrderEvent.objects.create(order=issue.order, kind=OrderEvent.Kind.ISSUE_SOLVED, user=user,
                              detail=f'{issue.text} — {resolution}')
    return issue


@transaction.atomic
def add_photo(order, user, image, item=None, caption=''):
    photo = OrderPhoto.objects.create(order=order, item=item, image=image, caption=caption, uploaded_by=user)
    OrderEvent.objects.create(order=order, kind=OrderEvent.Kind.PHOTO_ADDED, user=user, detail=caption)
    return photo


# --- Board -------------------------------------------------------------------

DUE_FILTERS = ('overdue', 'today', 'tomorrow')


def exclude_archived(queryset, store, now=None):
    """Leave out Ready / Collected orders older than the store's archive settings."""
    now = now or timezone.now()
    if store.archive_ready_after_days is not None:
        cutoff = now - datetime.timedelta(days=store.archive_ready_after_days)
        queryset = queryset.exclude(status=Order.Status.READY, cleaned_at__lt=cutoff)
    if store.archive_collected_after_days is not None:
        cutoff = now - datetime.timedelta(days=store.archive_collected_after_days)
        queryset = queryset.exclude(status=Order.Status.COLLECTED, collected_at__lt=cutoff)
    return queryset


def filter_due(queryset, store, when, now=None):
    """Orders due today / tomorrow (store's local days), or overdue (due before now)."""
    now = now or timezone.now()
    if when == 'overdue':
        return queryset.filter(due_at__lt=now)
    today = now.astimezone(store.tz).date()
    day = today if when == 'today' else today + datetime.timedelta(days=1)
    start = datetime.datetime.combine(day, datetime.time(), tzinfo=store.tz)
    return queryset.filter(due_at__gte=max(start, now) if when == 'today' else start,
                           due_at__lt=start + datetime.timedelta(days=1))


def search_orders(queryset, store, text):
    """Match an order number exactly, or the customer's phone / name / email."""
    text = text.strip().lstrip('#')
    customers = search_customers(Customer.objects.filter(company=store.company_id), text)
    condition = Q(customer__in=customers)
    if text.isdigit():
        condition |= Q(number=int(text))
    return queryset.filter(condition)


def board_totals(queryset):
    """Orders, pieces, bags and weight across the (filtered) orders."""
    items = OrderItem.objects.filter(order__in=queryset)
    sums = items.aggregate(pieces=Sum('pieces'), weight=Sum('weight'))
    return {
        'orders': queryset.count(),
        'pieces': sums['pieces'] or 0,
        'bags': queryset.aggregate(n=Sum('bags'))['n'] or 0,
        'weight': f"{sums['weight'] or 0:.2f}",
    }


def home_summary(orders, store, now=None):
    """The Home screen's cards: what's in Detailing, and Cleaning orders overdue / due today / tomorrow."""
    now = now or timezone.now()
    cleaning = orders.filter(status=Order.Status.CLEANING)
    return {
        'detailing': board_totals(orders.filter(status=Order.Status.DETAILING)),
        'cleaning': {when: board_totals(filter_due(cleaning, store, when, now)) for when in DUE_FILTERS},
    }


def customer_overview(customer):
    """Totals for a customer's profile. Deleted orders don't count."""
    orders = customer.orders.filter(deleted_at__isnull=True)
    sums = orders.aggregate(n=Count('id'), value=Sum('total'))
    count, value = sums['n'], sums['value'] or ZERO
    return {
        'total_orders': count,
        'lifetime_value': value,
        'average_order': money(value / count) if count else ZERO,
        'active_orders': orders.exclude(status=Order.Status.COLLECTED),
    }
