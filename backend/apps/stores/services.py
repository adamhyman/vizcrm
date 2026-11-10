import datetime
import ipaddress


def _counts_towards_turnaround(day, excluded_weekdays, closed_dates):
    return day.weekday() not in excluded_weekdays and day not in closed_dates


def due_at(store, dropped_off_at, express=False, extra_days=0):
    """When an order dropped off at `dropped_off_at` will be ready.

    Counts forward `turnaround_days` (or the express turnaround) plus `extra_days`,
    skipping the store's excluded weekdays and closed dates, and returns that day at
    the store's ready time (or express ready time), in the store's timezone.
    Drop-offs at or after the store's cutoff time get one extra day.

    With a zero-day turnaround the order is due the same day, unless it arrives on a
    non-counting day or too late (at or after the cutoff time, or the ready time if
    there is no cutoff), in which case it moves to the next counting day.
    """
    days = store.turnaround_days
    if express and store.express_turnaround_days is not None:
        days = store.express_turnaround_days
    days += extra_days
    ready_time = store.ready_time
    if express and store.express_ready_time is not None:
        ready_time = store.express_ready_time

    local = dropped_off_at.astimezone(store.tz)
    excluded = set(store.turnaround_excluded_weekdays)
    closed = set(store.closed_dates.filter(date__gte=local.date()).values_list('date', flat=True))

    day = local.date()
    after_cutoff = store.cutoff_time is not None and local.time() >= store.cutoff_time
    if days == 0:
        too_late = after_cutoff if store.cutoff_time is not None else local.time() >= ready_time
        if too_late or not _counts_towards_turnaround(day, excluded, closed):
            days = 1
    elif after_cutoff:
        days += 1
    while days > 0:
        day += datetime.timedelta(days=1)
        if _counts_towards_turnaround(day, excluded, closed):
            days -= 1

    return datetime.datetime.combine(day, ready_time, tzinfo=store.tz)


def client_ip(request):
    # REMOTE_ADDR is the connecting address. Behind a load balancer this will be the
    # proxy, so production must set it from a trusted X-Forwarded-For first.
    return request.META.get('REMOTE_ADDR', '')


def ip_allowed(store, ip):
    networks = store.allowed_networks()
    if not networks:
        return True
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(address in network for network in networks)
