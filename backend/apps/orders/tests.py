import datetime
from decimal import Decimal as D
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.models import PriceList, PriceListItem, Product, Section, Upcharge
from apps.contacts.models import Customer
from apps.stores.models import Store, TaxRate
from apps.stores.testing import create_staff, create_store

from .models import Order, OrderEvent, OrderIssue, OrderRevision
from .services import (
    NewItem, OrderError, add_item, create_order, delete_order, detail_order, edit_items, mark_cleaned,
    mark_collected, order_totals, report_issue,
)


class OrdersFixture(TestCase):
    def setUp(self):
        self.store = create_store(name='Main St', timezone='America/Los_Angeles')
        self.staff = create_staff('alex', self.store)
        self.dry = Section.objects.create(company=self.store.company, name='Dry Cleaning')
        self.laundry = Section.objects.create(company=self.store.company, name='Laundry')
        self.suit = Product.objects.create(section=self.dry, name='Suit', price=D('10.00'), pieces_per_unit=2)
        self.shirt = Product.objects.create(section=self.dry, name='Shirt', price=D('3.00'), express_price=D('4.00'))
        self.wash = Product.objects.create(
            section=self.laundry, name='Laundry per lb', price=D('2.00'), pricing_unit=Product.PricingUnit.WEIGHT,
            minimum_price=D('15.00'),
        )
        self.stain = Upcharge.objects.create(company=self.store.company, name='Stain', amount=D('3.00'))
        self.delicate = Upcharge.objects.create(company=self.store.company, name='Delicate', kind='percent', amount=D('25'))
        self.jane = Customer.objects.create(company=self.store.company, first_name='Jane', last_name='Smith', phone='310 555 0123')

    def order(self, *items, customer=None, **kwargs):
        return create_order(self.store, self.staff, customer or self.jane, list(items), **kwargs)


class PricingTests(OrdersFixture):
    def test_product_prices(self):
        order = self.order(NewItem(self.suit), NewItem(self.shirt))
        self.assertEqual([i.price for i in order.items.all()], [D('10.00'), D('3.00')])
        self.assertEqual(order.subtotal, D('13.00'))

    def test_express_uses_express_price(self):
        order = self.order(NewItem(self.suit), NewItem(self.shirt), express=True)
        self.assertEqual([i.price for i in order.items.all()], [D('15.00'), D('4.00')])

    def test_customer_price_list(self):
        hotel = PriceList.objects.create(company=self.store.company, name='Hotel')
        PriceListItem.objects.create(price_list=hotel, product=self.suit, price=D('8.00'))
        self.jane.price_list = hotel
        order = self.order(NewItem(self.suit))
        self.assertEqual((order.items.get().price, order.price_list), (D('8.00'), hotel))

    def test_weight_priced_with_minimum(self):
        heavy = self.order(NewItem(self.wash, weight=D('10')))
        self.assertEqual(heavy.items.get().price, D('20.00'))
        light = self.order(NewItem(self.wash, weight=D('3')))
        self.assertEqual(light.items.get().price, D('15.00'))

    def test_upcharges_fixed_and_percent(self):
        item = self.order(NewItem(self.suit, upcharges=[self.stain, self.delicate])).items.get()
        self.assertEqual(item.upcharges, [
            {'name': 'Stain', 'amount': '3.00', 'percent': None},
            {'name': 'Delicate', 'amount': '2.50', 'percent': '25'},
        ])
        self.assertEqual(item.price, D('15.50'))

    def test_price_override(self):
        item = self.order(NewItem(self.suit, price=D('7.00'))).items.get()
        self.assertEqual((item.price, item.price_overridden), (D('7.00'), True))

    def test_custom_item(self):
        item = self.order(NewItem(name='Wedding dress', price=D('80.00'), section=self.dry)).items.get()
        self.assertEqual((item.name, item.price, item.product, item.price_overridden), ('Wedding dress', D('80.00'), None, False))

    def test_pieces_follow_product(self):
        self.assertEqual(self.order(NewItem(self.suit)).items.get().pieces, 2)

    def test_customer_discount_and_exclusive_tax(self):
        TaxRate.objects.create(store=self.store, position=1, name='State', rate=D('6'))
        TaxRate.objects.create(store=self.store, position=2, name='City', rate=D('2.5'))
        self.jane.discount_percent = D('10')
        order = self.order(NewItem(self.suit), NewItem(self.suit))
        self.assertEqual((order.subtotal, order.discount), (D('20.00'), D('2.00')))
        self.assertEqual([t['amount'] for t in order.taxes], ['1.08', '0.45'])
        self.assertEqual((order.tax, order.total), (D('1.53'), D('19.53')))

    def test_inclusive_tax_is_part_of_total(self):
        self.store.tax_mode = Store.TaxMode.INCLUSIVE
        TaxRate.objects.create(store=self.store, position=1, name='VAT', rate=D('20'))
        totals = order_totals(self.store, [D('12.00')], D('0'))
        self.assertEqual((totals['tax'], totals['total']), (D('2.00'), D('12.00')))

    def test_needs_items(self):
        with self.assertRaises(OrderError):
            self.order()


class LifecycleTests(OrdersFixture):
    def test_numbers_count_up_per_store(self):
        other = create_store(name='Elsewhere')
        other_customer = Customer.objects.create(company=other.company, first_name='Sam', phone='1')
        self.assertEqual([self.order(NewItem(self.suit)).number for _ in range(2)], [1, 2])
        self.assertEqual(create_order(other, None, other_customer, [NewItem(name='X', price=D('1'))]).number, 1)

    def test_due_date_from_store_turnaround_plus_extra_days(self):
        self.shirt.extra_days = 1
        dropped_off = datetime.datetime(2026, 11, 9, 10, tzinfo=self.store.tz)  # a Monday
        with mock.patch('apps.orders.services.timezone.now', return_value=dropped_off):
            order = self.order(NewItem(self.suit), NewItem(self.shirt))
        self.assertEqual(order.due_at, datetime.datetime(2026, 11, 12, 17, tzinfo=self.store.tz))

    def test_given_due_date_wins(self):
        due = timezone.now() + datetime.timedelta(days=5)
        self.assertEqual(self.order(NewItem(self.suit), due_at=due).due_at, due)

    def test_cleaned_then_collected(self):
        order = self.order(NewItem(self.suit))
        mark_cleaned(order, self.staff, rack='A-42', bags=1, hanging=2)
        self.assertEqual((order.status, order.rack), (Order.Status.READY, 'A-42'))
        mark_collected(order, self.staff)
        self.assertEqual(order.status, Order.Status.COLLECTED)
        self.assertEqual(
            list(order.events.values_list('kind', 'detail')),
            [('created', ''), ('cleaned', 'Rack A-42'), ('collected', '')],
        )

    def test_out_of_order_steps_rejected(self):
        order = self.order(NewItem(self.suit))
        with self.assertRaises(OrderError):
            mark_collected(order, self.staff)
        mark_cleaned(order, self.staff, rack='1')
        with self.assertRaises(OrderError):
            mark_cleaned(order, self.staff, rack='1')

    def test_issue_records_stage(self):
        order = self.order(NewItem(self.suit))
        issue = report_issue(order, self.staff, 'Stain remains')
        self.assertEqual((issue.stage, issue.solved), ('cleaning', False))


class OrderSettingsTests(OrdersFixture):
    def test_store_default_price_list(self):
        hotel = PriceList.objects.create(company=self.store.company, name='Hotel')
        PriceListItem.objects.create(price_list=hotel, product=self.suit, price=D('8.00'))
        self.store.default_price_list = hotel
        self.store.save()
        self.jane.refresh_from_db()
        self.assertEqual(self.order(NewItem(self.suit)).subtotal, D('8.00'))

    def test_first_order_discount(self):
        self.store.first_order_discount_percent = D('20')
        self.assertEqual(self.order(NewItem(self.suit)).discount, D('2.00'))
        self.assertEqual(self.order(NewItem(self.suit)).discount, D('0.00'))

    def test_first_order_discount_only_when_bigger(self):
        self.store.first_order_discount_percent = D('20')
        self.jane.discount_percent = D('30')
        self.assertEqual(self.order(NewItem(self.suit)).discount, D('3.00'))

    def test_deleted_orders_dont_count_as_earlier_orders(self):
        self.store.first_order_discount_percent = D('20')
        delete_order(self.order(NewItem(self.suit)), self.staff)
        self.assertEqual(self.order(NewItem(self.suit)).discount, D('2.00'))

    def test_minimum_order_amount(self):
        self.store.minimum_order_amount = D('15.00')
        self.store.minimum_express_order_amount = D('25.00')
        order = self.order(NewItem(self.suit))
        self.assertEqual((order.subtotal, order.minimum_charge, order.total), (D('10.00'), D('5.00'), D('15.00')))
        express = self.order(NewItem(self.suit), express=True)
        self.assertEqual((express.minimum_charge, express.total), (D('10.00'), D('25.00')))
        self.assertEqual(self.order(NewItem(self.suit), NewItem(self.suit)).minimum_charge, D('0.00'))

    def test_minimum_not_applied_before_itemising_or_to_retail(self):
        self.store.minimum_order_amount = D('15.00')
        self.assertEqual(self.order(type=Order.Type.QUICK_DROP).total, D('0.00'))
        retail = Section.objects.create(company=self.store.company, name='Retail', retail=True)
        roller = Product.objects.create(section=retail, name='Lint Roller', price=D('5.00'))
        sale = create_order(self.store, self.staff, None, [NewItem(roller)], type=Order.Type.RETAIL)
        self.assertEqual(sale.total, D('5.00'))

    def test_rack_required_by_default(self):
        order = self.order(NewItem(self.suit))
        with self.assertRaises(OrderError):
            mark_cleaned(order, self.staff)
        self.store.require_rack_when_cleaned = False
        mark_cleaned(order, self.staff)
        self.assertEqual(order.status, Order.Status.READY)

    def test_bags_and_hanging_required_when_set(self):
        self.store.require_bags_when_cleaned = True
        order = self.order(NewItem(self.suit))
        with self.assertRaises(OrderError):
            mark_cleaned(order, self.staff, rack='1', bags=1)
        mark_cleaned(order, self.staff, rack='1', bags=1, hanging=0)
        self.assertEqual((order.bags, order.hanging), (1, 0))

    def test_reweigh_when_collected_reprices(self):
        self.store.reweigh_when_collected = True
        order = self.order(NewItem(self.wash, weight=D('10'), upcharges=[self.delicate]))
        mark_cleaned(order, self.staff, rack='1')
        item = order.items.get()
        with self.assertRaises(OrderError):
            mark_collected(order, self.staff)
        mark_collected(order, self.staff, weights={item.pk: D('12')})
        item.refresh_from_db()
        self.assertEqual((item.weight, item.price, order.subtotal), (D('12'), D('30.00'), D('30.00')))
        self.assertEqual(order.revisions.first().changes, 'Weights')

    def test_reweigh_keeps_minimum_and_overridden_prices(self):
        order = self.order(NewItem(self.wash, weight=D('10')), NewItem(self.wash, weight=D('10'), price=D('5')))
        mark_cleaned(order, self.staff, rack='1', weights={i.pk: D('2') for i in order.items.all()})
        self.assertEqual([i.price for i in order.items.all()], [D('15.00'), D('5.00')])

    def test_only_weight_items_can_be_reweighed(self):
        order = self.order(NewItem(self.suit))
        with self.assertRaises(OrderError):
            mark_cleaned(order, self.staff, rack='1', weights={order.items.get().pk: D('2')})

    def test_edit_items_keeps_order_pricing(self):
        self.jane.discount_percent = D('10')
        order = self.order(NewItem(self.suit))
        self.jane.discount_percent = D('0')
        edit_items(order, self.staff, [NewItem(self.suit), NewItem(self.suit)])
        self.assertEqual((order.subtotal, order.discount), (D('20.00'), D('2.00')))
        self.assertEqual(order.items.count(), 2)

    def test_collected_and_deleted_orders_cant_be_edited(self):
        order = self.order(NewItem(self.suit))
        delete_order(order, self.staff)
        with self.assertRaises(OrderError):
            edit_items(order, self.staff, [NewItem(self.shirt)])
        collected = self.order(NewItem(self.suit))
        mark_cleaned(collected, self.staff, rack='1')
        mark_collected(collected, self.staff)
        with self.assertRaises(OrderError):
            edit_items(collected, self.staff, [NewItem(self.shirt)])

    def test_revisions(self):
        order = self.order(type=Order.Type.QUICK_DROP, bags=2)
        detail_order(order, self.staff, [NewItem(self.suit)])
        self.assertEqual(
            list(OrderRevision.objects.values_list('created', 'summary', 'changes').order_by('id')),
            [(True, '2 bags', ''), (False, 'Suit', 'Items (detailing)')],
        )

    def test_archived_orders_hidden_from_board(self):
        client = APIClient()
        client.force_authenticate(self.staff)
        order = self.order(NewItem(self.suit))
        mark_cleaned(order, self.staff, rack='1')
        Order.objects.filter(pk=order.pk).update(cleaned_at=timezone.now() - datetime.timedelta(days=31))
        self.store.archive_ready_after_days = 30
        self.store.save()
        self.assertEqual(client.get('/api/orders/').json()['count'], 0)
        self.assertEqual(client.get('/api/orders/totals/').json()['orders'], 0)
        self.assertEqual(client.get('/api/orders/?include_archived=true').json()['count'], 1)


class DetailingTests(OrdersFixture):
    QUICK = Order.Type.QUICK_DROP

    def test_in_store_orders_skip_detailing_by_default(self):
        self.assertEqual(self.order(NewItem(self.suit)).status, Order.Status.CLEANING)

    def test_quick_drop_starts_in_detailing_then_gets_items(self):
        order = self.order(type=self.QUICK, bags=2, notes='Two bags')
        self.assertEqual((order.status, order.bags, order.total, order.items.count()), ('detailing', 2, D('0'), 0))
        detail_order(order, self.staff, [NewItem(self.suit), NewItem(self.shirt)])
        self.assertEqual((order.status, order.subtotal), (Order.Status.CLEANING, D('13.00')))
        self.assertEqual(order.events.last().detail, '3 pieces')

    def test_detailing_reprices_with_order_price_list_and_discount(self):
        hotel = PriceList.objects.create(company=self.store.company, name='Hotel')
        PriceListItem.objects.create(price_list=hotel, product=self.suit, price=D('8.00'))
        self.jane.price_list, self.jane.discount_percent = hotel, D('50')
        self.jane.save()
        order = self.order(type=self.QUICK)
        detail_order(order, self.staff, [NewItem(self.suit)])
        self.assertEqual((order.subtotal, order.total), (D('8.00'), D('4.00')))

    def test_quick_drop_must_be_itemised(self):
        order = self.order(type=self.QUICK)
        with self.assertRaises(OrderError):
            detail_order(order, self.staff)
        with self.assertRaises(OrderError):
            self.order(NewItem(self.suit), type=self.QUICK)

    def test_quick_drop_can_be_turned_off(self):
        self.store.quick_drop_enabled = False
        with self.assertRaises(OrderError):
            self.order(type=self.QUICK)

    def test_all_in_store_orders_to_detailing(self):
        self.store.detailing_orders = Store.DetailingOrders.ALL
        order = self.order(NewItem(self.suit))
        self.assertEqual(order.status, Order.Status.DETAILING)
        detail_order(order, self.staff)  # keeps its items
        self.assertEqual((order.status, order.items.count()), (Order.Status.CLEANING, 1))

    def test_detailing_limited_to_sections(self):
        self.store.detailing_orders = Store.DetailingOrders.ALL
        self.store.save()
        self.store.detailing_sections.add(self.laundry)
        self.assertEqual(self.order(NewItem(self.suit)).status, Order.Status.CLEANING)
        self.assertEqual(self.order(NewItem(self.suit), NewItem(self.wash, weight=D('8'))).status, 'detailing')

    def test_detailing_stage_off(self):
        self.store.detailing_enabled = False
        self.store.quick_drop_enabled = False
        self.store.detailing_orders = Store.DetailingOrders.ALL
        self.assertEqual(self.order(NewItem(self.suit)).status, Order.Status.CLEANING)

    def test_only_detailing_orders_can_be_detailed(self):
        with self.assertRaises(OrderError):
            detail_order(self.order(NewItem(self.suit)), self.staff)


class RetailTests(OrdersFixture):
    def setUp(self):
        super().setUp()
        self.retail = Section.objects.create(company=self.store.company, name='Retail', retail=True)
        self.roller = Product.objects.create(section=self.retail, name='Lint Roller', price=D('5.00'))

    def sale(self, *items, customer=None):
        return create_order(self.store, self.staff, customer, list(items), type=Order.Type.RETAIL)

    def test_walk_in_sale_is_complete_at_once(self):
        order = self.sale(NewItem(self.roller), NewItem(name='Hanger', price=D('1.00')))
        self.assertEqual((order.status, order.total, order.customer.walk_in), ('collected', D('6.00'), True))
        self.assertEqual(list(order.events.values_list('kind', flat=True)), ['created', 'collected'])
        self.assertEqual(self.sale(NewItem(self.roller)).customer, order.customer)

    def test_sale_to_known_customer(self):
        self.assertEqual(self.sale(NewItem(self.roller), customer=self.jane).customer, self.jane)

    def test_retail_goods_can_count_zero_pieces(self):
        self.roller.pieces_per_unit = 0
        self.roller.save()
        self.assertEqual(self.sale(NewItem(self.roller)).items.get().pieces, 0)

    def test_only_retail_items(self):
        with self.assertRaises(OrderError):
            self.sale(NewItem(self.suit))

    def test_other_order_types_need_a_customer(self):
        with self.assertRaises(OrderError):
            create_order(self.store, self.staff, None, [NewItem(self.suit)])


class OrderApiTests(OrdersFixture):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.staff)
        self.other_store = create_store(name='Elsewhere')
        other_section = Section.objects.create(company=self.other_store.company, name='Dry Cleaning')
        self.other_product = Product.objects.create(section=other_section, name='Secret', price=D('1.00'))

    def post_order(self, items, **extra):
        return self.client.post('/api/orders/', {'customer': self.jane.pk, 'items': items, **extra}, format='json')

    def test_create(self):
        response = self.post_order([
            {'product': self.suit.pk, 'colors': ['Navy'], 'damages': ['Hole'], 'barcode': '1001',
             'upcharges': [self.stain.pk]},
            {'product': self.wash.pk, 'weight': '8'},
            {'name': 'Rug', 'price': '25.00', 'section': self.laundry.pk},
        ], express=False, notes='Light starch')
        self.assertEqual(response.status_code, 201, response.json())
        body = response.json()
        self.assertEqual((body['number'], body['status'], body['subtotal']), (1, 'cleaning', '54.00'))
        self.assertEqual(body['items'][0]['colors'], ['Navy'])
        self.assertEqual([e['kind'] for e in body['events']], ['created'])

    def test_item_validation(self):
        cases = [
            ({'product': self.wash.pk}, 'weight'),
            ({'product': self.suit.pk, 'weight': '2'}, 'weight'),
            ({'name': 'Rug'}, 'price'),
            ({'product': self.suit.pk, 'colors': ['Plaid-ish']}, 'colors'),
            ({'product': self.suit.pk, 'damages': ['Hole', 'Tear', 'Burn', 'Snag']}, 'damages'),
            ({'product': self.suit.pk, 'colors': ['Navy', 'Black', 'Red']}, 'colors'),
            ({'product': self.other_product.pk}, 'product'),
        ]
        for item, field in cases:
            with self.subTest(item=item):
                response = self.post_order([item])
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json()['items']['0'])

    def test_inactive_product_rejected(self):
        self.suit.active = False
        self.suit.save()
        self.assertEqual(self.post_order([{'product': self.suit.pk}]).status_code, 400)

    def test_upcharge_must_be_offered_on_product(self):
        self.stain.products.add(self.shirt)
        self.assertEqual(self.post_order([{'product': self.suit.pk, 'upcharges': [self.stain.pk]}]).status_code, 400)
        self.assertEqual(self.post_order([{'product': self.shirt.pk, 'upcharges': [self.stain.pk]}]).status_code, 201)

    def test_cannot_order_for_other_store_customer(self):
        stranger = Customer.objects.create(company=self.other_store.company, first_name='Sam', phone='1')
        response = self.client.post(
            '/api/orders/', {'customer': stranger.pk, 'items': [{'product': self.suit.pk}]}, format='json'
        )
        self.assertEqual(response.status_code, 400)

    def test_board_filters_and_totals(self):
        suit_order = self.order(NewItem(self.suit))
        wash_order = self.order(NewItem(self.wash, weight=D('8')))
        mark_cleaned(suit_order, self.staff, rack='3')
        report_issue(wash_order, self.staff, 'Missing sock')
        report_issue(wash_order, self.staff, 'Torn bag')

        rows = self.client.get('/api/orders/?status=cleaning').json()['results']
        self.assertEqual([(r['number'], r['pieces'], r['open_issues']) for r in rows], [(2, 1, 2)])
        rows = self.client.get(f'/api/orders/?section={self.dry.pk}').json()['results']
        self.assertEqual([r['number'] for r in rows], [1])

        totals = self.client.get('/api/orders/totals/').json()
        self.assertEqual((totals['orders'], totals['pieces'], totals['weight']), (2, 3, '8.00'))

    def test_board_search(self):
        self.order(NewItem(self.suit))
        bob = Customer.objects.create(company=self.store.company, first_name='Bob', phone='818 555 9876')
        self.order(NewItem(self.suit), customer=bob)
        search = lambda text: [r['number'] for r in self.client.get(f'/api/orders/?search={text}').json()['results']]
        self.assertEqual(search('%232'), [2])  # "#2"
        self.assertEqual(search('818-555'), [2])
        self.assertEqual(search('jane'), [1])

    def test_due_filters(self):
        now = timezone.now()
        overdue = self.order(NewItem(self.suit), due_at=now - datetime.timedelta(hours=1))
        later = self.order(NewItem(self.suit), due_at=now + datetime.timedelta(days=3))
        numbers = [r['number'] for r in self.client.get('/api/orders/?due=overdue').json()['results']]
        self.assertEqual(numbers, [overdue.number])
        self.assertNotIn(later.number, [r['number'] for r in self.client.get('/api/orders/?due=today').json()['results']])

    def test_mark_cleaned_and_collected(self):
        order = self.order(NewItem(self.suit))
        response = self.client.post(f'/api/orders/{order.pk}/mark-cleaned/', {'rack': 'A-42', 'bags': 1}, format='json')
        self.assertEqual((response.status_code, response.json()['status']), (200, 'ready'))
        self.assertEqual(self.client.post(f'/api/orders/{order.pk}/mark-cleaned/').status_code, 409)
        self.assertEqual(self.client.post(f'/api/orders/{order.pk}/mark-collected/').json()['status'], 'collected')

    def test_edit_notes_is_on_timeline(self):
        order = self.order(NewItem(self.suit))
        response = self.client.patch(f'/api/orders/{order.pk}/', {'notes': 'Call when ready', 'total': '0'}, format='json')
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual((order.notes, order.total), ('Call when ready', D('10.00')))
        self.assertEqual(order.events.last().kind, OrderEvent.Kind.EDITED)

    def test_delete_hides_order_and_logs_it(self):
        order = self.order(NewItem(self.suit))
        report_issue(order, self.staff, 'Stain remains')
        self.assertEqual(self.client.delete(f'/api/orders/{order.pk}/').status_code, 204)
        self.assertEqual(self.client.get(f'/api/orders/{order.pk}/').status_code, 404)
        self.assertEqual(self.client.get('/api/orders/').json()['count'], 0)
        self.assertEqual(self.client.get('/api/order-issues/').json()['count'], 0)
        rows = self.client.get('/api/order-deletions/').json()['results']
        self.assertEqual([(r['number'], r['deleted_by'], r['summary']) for r in rows], [(1, 'alex', 'Suit')])
        # Numbers aren't reused.
        self.assertEqual(self.order(NewItem(self.suit)).number, 2)

    def test_edit_items(self):
        order = self.order(NewItem(self.suit))
        response = self.client.post(f'/api/orders/{order.pk}/edit-items/', {
            'items': [{'product': self.suit.pk}, {'product': self.shirt.pk}], 'express': True,
        }, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual((response.json()['total'], response.json()['express']), ('19.00', True))
        self.assertEqual(response.json()['events'][-1]['detail'], 'Items changed; total 10.00 → 19.00')

    def test_order_edits_log(self):
        order = self.order(NewItem(self.suit))
        self.client.patch(f'/api/orders/{order.pk}/', {'notes': 'Call first'}, format='json')
        rows = self.client.get(f'/api/order-edits/?search=%23{order.number}').json()['results']
        self.assertEqual([(r['created'], r['changes'], r['summary'], r['total']) for r in rows],
                         [(False, 'Notes', 'Suit', '10.00'), (True, '', 'Suit', '10.00')])
        today = timezone.now().astimezone(self.store.tz).date()
        self.assertEqual(self.client.get(f'/api/order-edits/?since={today}').json()['count'], 2)
        tomorrow = today + datetime.timedelta(days=1)
        self.assertEqual(self.client.get(f'/api/order-edits/?since={tomorrow}').json()['count'], 0)
        self.assertEqual(self.client.get(f'/api/order-edits/?user={self.staff.pk + 1}').json()['count'], 0)

    def test_mark_cleaned_with_weights(self):
        self.store.reweigh_when_cleaned = True
        self.store.save()
        order = self.order(NewItem(self.wash, weight=D('8')))
        item = order.items.get()
        url = f'/api/orders/{order.pk}/mark-cleaned/'
        self.assertEqual(self.client.post(url, {'rack': 'A1'}, format='json').status_code, 409)
        response = self.client.post(url, {'rack': 'A1', 'weights': {str(item.pk): '9.5'}}, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual((response.json()['items'][0]['weight'], response.json()['subtotal']), ('9.50', '19.00'))

    def test_issues(self):
        order = self.order(NewItem(self.suit))
        issue_id = self.client.post(
            f'/api/orders/{order.pk}/report-issue/', {'text': 'Stain remains'}, format='json'
        ).json()['id']
        open_issues = self.client.get('/api/order-issues/?solved=false').json()['results']
        self.assertEqual([i['text'] for i in open_issues], ['Stain remains'])
        url = f'/api/order-issues/{issue_id}/mark-solved/'
        self.assertEqual(self.client.post(url).status_code, 400)  # needs an explanation
        solved = {'resolution': 'Re-cleaned'}
        self.assertEqual(self.client.post(url, solved, format='json').status_code, 200)
        self.assertEqual(self.client.post(url, solved, format='json').status_code, 409)
        self.assertEqual(self.client.get('/api/order-issues/?solved=false').json()['count'], 0)
        issue = OrderIssue.objects.get(pk=issue_id)
        self.assertEqual((issue.solved, issue.resolution), (True, 'Re-cleaned'))

    def test_new_issue_from_issues_tab(self):
        order = self.order(NewItem(self.suit))
        response = self.client.post('/api/order-issues/', {'order': order.pk, 'text': 'Missing sock'}, format='json')
        self.assertEqual((response.status_code, response.json()['order_number']), (201, order.number))
        stranger = Customer.objects.create(company=self.other_store.company, first_name='Sam', phone='1')
        theirs = create_order(self.other_store, None, stranger, [NewItem(self.other_product)])
        response = self.client.post('/api/order-issues/', {'order': theirs.pk, 'text': 'x'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_delete_with_reason(self):
        order = self.order(NewItem(self.suit))
        self.client.delete(f'/api/orders/{order.pk}/', {'reason': 'Duplicate'}, format='json')
        row = self.client.get('/api/order-deletions/').json()['results'][0]
        self.assertEqual(row['deletion_reason'], 'Duplicate')

    def test_photos(self):
        import io
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        buffer = io.BytesIO()
        Image.new('RGB', (2, 2)).save(buffer, 'PNG')
        order = self.order(NewItem(self.suit))
        other = self.order(NewItem(self.shirt))
        with self.settings(MEDIA_ROOT=self.enterContext(__import__('tempfile').TemporaryDirectory())):
            upload = lambda **extra: self.client.post(f'/api/orders/{order.pk}/photos/', {
                'image': SimpleUploadedFile('tear.png', buffer.getvalue(), 'image/png'), 'caption': 'Tear', **extra,
            }, format='multipart')
            self.assertEqual(upload(item=other.items.get().pk).status_code, 400)
            self.assertEqual(upload(item=order.items.get().pk).status_code, 201)
            body = self.client.get(f'/api/orders/{order.pk}/').json()
        self.assertEqual([p['caption'] for p in body['photos']], ['Tear'])
        self.assertEqual(body['events'][-1]['kind'], 'photo_added')

    def test_price_list_chosen_for_order(self):
        hotel = PriceList.objects.create(company=self.store.company, name='Hotel')
        PriceListItem.objects.create(price_list=hotel, product=self.suit, price=D('8.00'))
        response = self.post_order([{'product': self.suit.pk}], price_list=hotel.pk)
        self.assertEqual(response.json()['subtotal'], '8.00')

    def test_product_limited_to_price_lists(self):
        hotel = PriceList.objects.create(company=self.store.company, name='Hotel')
        vip = PriceList.objects.create(company=self.store.company, name='VIP')
        self.suit.price_lists.add(vip)
        self.assertEqual(self.post_order([{'product': self.suit.pk}], price_list=hotel.pk).status_code, 400)
        self.assertEqual(self.post_order([{'product': self.suit.pk}], price_list=vip.pk).status_code, 201)
        self.assertEqual(self.post_order([{'product': self.suit.pk}]).status_code, 201)  # product prices
        names = [p['name'] for p in self.client.get(f'/api/products/?price_list={hotel.pk}').json()]
        self.assertNotIn('Suit', names)

    def test_home_summary(self):
        now = timezone.now()
        self.order(type=Order.Type.QUICK_DROP, bags=2)
        self.order(NewItem(self.suit), due_at=now - datetime.timedelta(hours=1))
        body = self.client.get('/api/orders/home/').json()
        self.assertEqual((body['detailing']['orders'], body['detailing']['bags']), (1, 2))
        self.assertEqual((body['cleaning']['overdue']['orders'], body['cleaning']['overdue']['pieces']), (1, 2))
        self.assertEqual(body['last_order']['number'], 2)

    def test_customer_overview(self):
        first = self.order(NewItem(self.suit))
        self.order(NewItem(self.shirt))
        mark_cleaned(first, self.staff, rack='1')
        mark_collected(first, self.staff)
        delete_order(self.order(NewItem(self.suit)), self.staff)
        body = self.client.get(f'/api/customers/{self.jane.pk}/overview/').json()
        self.assertEqual((body['total_orders'], body['lifetime_value'], body['average_order']), (2, '13.00', '6.50'))
        self.assertEqual([o['number'] for o in body['active_orders']], [2])
        stranger = Customer.objects.create(company=self.other_store.company, first_name='Sam', phone='1')
        self.assertEqual(self.client.get(f'/api/customers/{stranger.pk}/overview/').status_code, 404)

    def test_other_store_orders_hidden(self):
        stranger = Customer.objects.create(company=self.other_store.company, first_name='Sam', phone='1')
        theirs = create_order(self.other_store, None, stranger, [NewItem(self.other_product)])
        self.assertEqual(self.client.get('/api/orders/').json()['count'], 0)
        self.assertEqual(self.client.get(f'/api/orders/{theirs.pk}/').status_code, 404)

    def test_quick_drop_then_detail(self):
        response = self.client.post('/api/orders/', {'type': 'quick_drop', 'customer': self.jane.pk, 'bags': 2},
                                    format='json')
        self.assertEqual((response.status_code, response.json()['status']), (201, 'detailing'))
        order_id = response.json()['id']
        self.assertEqual(self.client.post(f'/api/orders/{order_id}/detail/', {}, format='json').status_code, 409)
        response = self.client.post(
            f'/api/orders/{order_id}/detail/', {'items': [{'product': self.suit.pk, 'colors': ['Black']}]}, format='json'
        )
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual((response.json()['status'], response.json()['total']), ('cleaning', '10.00'))

    def test_order_rules_are_400(self):
        response = self.client.post('/api/orders/', {'customer': self.jane.pk, 'items': []}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_retail_sale_without_customer(self):
        retail = Section.objects.create(company=self.store.company, name='Retail', retail=True)
        roller = Product.objects.create(section=retail, name='Lint Roller', price=D('5.00'))
        response = self.client.post('/api/orders/', {'type': 'retail', 'items': [{'product': roller.pk}]}, format='json')
        self.assertEqual(response.status_code, 201, response.json())
        self.assertEqual((response.json()['status'], response.json()['customer']['full_name']),
                         ('collected', 'Retail customer'))

    def test_store_settings_quick_drop_needs_detailing(self):
        response = self.client.patch('/api/store/', {'detailing_enabled': False}, format='json')
        self.assertEqual(response.status_code, 400)
        response = self.client.patch('/api/store/', {'detailing_enabled': False, 'quick_drop_enabled': False},
                                     format='json')
        self.assertEqual(response.status_code, 200)

    def test_store_settings_detailing_sections_must_be_own(self):
        other = Section.objects.get(company=self.other_store.company)
        response = self.client.patch('/api/store/', {'detailing_sections': [other.pk]}, format='json')
        self.assertEqual(response.status_code, 400)
        response = self.client.patch('/api/store/', {'detailing_sections': [self.laundry.pk]}, format='json')
        self.assertEqual(response.json()['detailing_sections'], [self.laundry.pk])

    def test_garment_options(self):
        body = self.client.get('/api/orders/garment-options/').json()
        self.assertIn({'name': 'Navy', 'hex': '#000080'}, body['colors'])
        self.assertEqual((body['max_choices']['colors'], body['max_choices']['damages']), (2, 3))


def form_data(html):
    """The fields a browser would submit for the page's form, as {name: value(s)}."""
    from html.parser import HTMLParser

    class Fields(HTMLParser):
        def __init__(self):
            super().__init__()
            self.data, self.select, self.textarea = {}, None, None

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            name = attrs.get('name')
            if tag == 'input' and name and attrs.get('type') not in ('submit', 'file', 'button'):
                if attrs.get('type') in ('checkbox', 'radio') and 'checked' not in attrs:
                    return
                self.data[name] = attrs.get('value', 'on' if attrs.get('type') == 'checkbox' else '')
            elif tag == 'select' and name:
                self.select = name
                self.data.setdefault(name, [] if 'multiple' in attrs else '')
            elif tag == 'option' and self.select and 'selected' in attrs:
                if isinstance(self.data[self.select], list):
                    self.data[self.select].append(attrs.get('value', ''))
                else:
                    self.data[self.select] = attrs.get('value', '')
            elif tag == 'textarea' and name:
                self.textarea = name
                self.data[name] = ''

        def handle_data(self, text):
            if self.textarea:
                self.data[self.textarea] += text

        def handle_endtag(self, tag):
            if tag == 'select':
                self.select = None
            elif tag == 'textarea':
                self.textarea = None

    parser = Fields()
    parser.feed(html)
    return {name: value.strip('\n') if isinstance(value, str) else value for name, value in parser.data.items()}


class AddItemTests(OrdersFixture):
    def test_add_item_prices_it_and_updates_totals(self):
        TaxRate.objects.create(store=self.store, position=1, name='Tax', rate=D('10'))
        order = self.order(NewItem(self.suit))
        item = add_item(order, self.staff, NewItem(self.wash, weight=D('10')))
        self.assertEqual((item.price, order.subtotal, order.total), (D('20.00'), D('30.00'), D('33.00')))
        self.assertEqual(order.events.last().detail, 'Added Laundry per lb; total 11.00 → 33.00')
        self.assertEqual(order.revisions.first().changes, 'Items')

    def test_cannot_add_to_collected_order(self):
        order = self.order(NewItem(self.suit))
        mark_cleaned(order, self.staff, rack='1')
        mark_collected(order, self.staff)
        with self.assertRaises(OrderError):
            add_item(order, self.staff, NewItem(self.shirt))


class OrderAdminTests(OrdersFixture):
    def setUp(self):
        super().setUp()
        from apps.accounts.models import User

        self.client.force_login(
            User.objects.create_superuser('boss', 'b@example.com', 'pw', company=self.store.company)
        )
        self.order_ = self.order(NewItem(self.suit))
        self.url = f'/admin/orders/order/{self.order_.pk}/change/'

    def submit(self, **item):
        data = form_data(self.client.get(self.url).content.decode())
        prefix = next(k for k in data if k.endswith('-0-product') and '__prefix__' not in k)[:-len('product')]
        data.update({prefix + field: value for field, value in item.items()})
        return self.client.post(self.url, data)

    def test_add_product_item(self):
        response = self.submit(product=self.shirt.pk)
        self.assertEqual(response.status_code, 302, response.context and response.context['errors'])
        self.order_.refresh_from_db()
        self.assertEqual([(i.name, i.price) for i in self.order_.items.all()],
                         [('Suit', D('10.00')), ('Shirt', D('3.00'))])
        self.assertEqual(self.order_.total, D('13.00'))

    def test_add_custom_and_weighed_items_validate(self):
        self.assertEqual(self.submit(name='Rug').status_code, 200)  # custom item needs a price
        self.assertEqual(self.submit(product=self.wash.pk).status_code, 200)  # needs a weight
        self.assertEqual(self.order_.items.count(), 1)
        self.assertEqual(self.submit(name='Rug', price='25.00').status_code, 302)
        self.assertEqual(self.submit(product=self.wash.pk, weight='10').status_code, 302)
        self.order_.refresh_from_db()
        self.assertEqual(self.order_.subtotal, D('55.00'))

    def test_saving_without_a_new_item_changes_nothing(self):
        self.assertEqual(self.submit().status_code, 302)
        self.assertEqual(self.order_.items.count(), 1)

    def test_other_company_products_are_not_offered(self):
        other = Section.objects.create(company=create_store('Elsewhere').company, name='Dry Cleaning')
        secret = Product.objects.create(section=other, name='Secret', price=D('1.00'))
        self.assertEqual(self.submit(product=secret.pk).status_code, 200)
        self.assertEqual(self.order_.items.count(), 1)
