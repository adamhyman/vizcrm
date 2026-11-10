from decimal import Decimal as D

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.stores.models import Store

from .models import PriceList, PriceListItem, Product, Section
from .services import BulkUpdateError, bulk_update_products, price_list_overrides, unit_price


class CatalogFixture(TestCase):
    def setUp(self):
        self.store = Store.objects.create(name='Main St')
        self.dry = Section.objects.create(store=self.store, name='Dry Cleaning', position=1)
        self.suit = Product.objects.create(section=self.dry, name='Suit', price=D('10.00'), pieces_per_unit=2)
        self.shirt = Product.objects.create(section=self.dry, name='Shirt', price=D('3.00'), express_price=D('4.00'))
        self.default_list = PriceList.objects.create(store=self.store, name='Default', is_default=True)
        self.hotel = PriceList.objects.create(store=self.store, name='Hotel')


class UnitPriceTests(CatalogFixture):
    def test_express_defaults_to_store_multiplier(self):
        self.assertEqual(unit_price(self.suit).express_price, D('15.00'))

    def test_explicit_express_price_wins(self):
        self.assertEqual(unit_price(self.shirt).express_price, D('4.00'))

    def test_express_multiplier_rounds_to_cents(self):
        self.store.express_multiplier = D('1.33')
        self.store.save()
        self.suit.price = D('9.99')
        self.assertEqual(unit_price(self.suit).express_price, D('13.29'))

    def test_price_list_override(self):
        PriceListItem.objects.create(price_list=self.hotel, product=self.suit, price=D('8.00'))
        prices = unit_price(self.suit, price_list_overrides(self.hotel))
        self.assertEqual((prices.price, prices.express_price), (D('8.00'), D('12.00')))

    def test_products_missing_from_price_list_use_own_price(self):
        PriceListItem.objects.create(price_list=self.hotel, product=self.suit, price=D('8.00'))
        self.assertEqual(unit_price(self.shirt, price_list_overrides(self.hotel)).price, D('3.00'))

    def test_default_price_list_has_no_overrides(self):
        self.assertEqual(price_list_overrides(self.default_list), {})

    def test_for_order(self):
        prices = unit_price(self.suit)
        self.assertEqual(prices.for_order(express=False), D('10.00'))
        self.assertEqual(prices.for_order(express=True), D('15.00'))


class BulkUpdateTests(CatalogFixture):
    def test_preview_does_not_save(self):
        changes = bulk_update_products(
            [self.suit, self.shirt], {'price': {'op': 'increase_amount', 'value': D('0.50')}}
        )
        self.assertEqual([(c['old'], c['new']) for c in changes], [(D('10.00'), D('10.50')), (D('3.00'), D('3.50'))])
        self.suit.refresh_from_db()
        self.assertEqual(self.suit.price, D('10.00'))

    def test_apply_saves(self):
        bulk_update_products([self.suit], {'price': {'op': 'increase_percent', 'value': D('5')}}, apply=True)
        self.suit.refresh_from_db()
        self.assertEqual(self.suit.price, D('10.50'))

    def test_percent_rounds_half_up(self):
        self.shirt.price = D('2.99')
        changes = bulk_update_products([self.shirt], {'price': {'op': 'increase_percent', 'value': D('5')}})
        self.assertEqual(changes[0]['new'], D('3.14'))  # 3.1395

    def test_never_goes_below_zero(self):
        changes = bulk_update_products([self.shirt], {'price': {'op': 'decrease_amount', 'value': D('5')}})
        self.assertEqual(changes[0]['new'], D('0.00'))

    def test_unchanged_values_are_not_listed(self):
        changes = bulk_update_products([self.suit, self.shirt], {'price': {'op': 'set', 'value': D('3.00')}})
        self.assertEqual([c['product'] for c in changes], ['Suit'])

    def test_derived_express_price_becomes_explicit(self):
        bulk_update_products(
            [self.suit], {'express_price': {'op': 'increase_amount', 'value': D('1')}}, apply=True
        )
        self.suit.refresh_from_db()
        self.assertEqual(self.suit.express_price, D('16.00'))

    def test_non_money_fields(self):
        bulk_update_products(
            [self.suit], {'extra_days': {'value': 2}, 'active': {'value': False}}, apply=True
        )
        self.suit.refresh_from_db()
        self.assertEqual((self.suit.extra_days, self.suit.active), (2, False))

    def test_price_list_target_creates_overrides(self):
        bulk_update_products(
            [self.suit], {'price': {'op': 'decrease_percent', 'value': D('10')}}, price_list=self.hotel, apply=True
        )
        item = PriceListItem.objects.get(price_list=self.hotel, product=self.suit)
        self.assertEqual(item.price, D('9.00'))
        self.suit.refresh_from_db()
        self.assertEqual(self.suit.price, D('10.00'))

    def test_price_list_target_updates_existing_override(self):
        PriceListItem.objects.create(price_list=self.hotel, product=self.suit, price=D('8.00'))
        bulk_update_products(
            [self.suit],
            {'price': {'op': 'increase_amount', 'value': D('1')},
             'express_price': {'op': 'set', 'value': D('11.00')}},
            price_list=self.hotel, apply=True,
        )
        item = PriceListItem.objects.get(price_list=self.hotel, product=self.suit)
        self.assertEqual((item.price, item.express_price), (D('9.00'), D('11.00')))

    def test_price_list_target_rejects_non_price_fields(self):
        with self.assertRaises(BulkUpdateError):
            bulk_update_products([self.suit], {'cost_price': {'op': 'set', 'value': D('1')}}, price_list=self.hotel)

    def test_requires_a_change(self):
        with self.assertRaises(BulkUpdateError):
            bulk_update_products([self.suit], {})


class CatalogApiTests(CatalogFixture):
    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_user('alex', password='pw', store=self.store)
        self.client = APIClient()
        self.client.force_authenticate(self.staff)

        other_store = Store.objects.create(name='Elsewhere')
        self.other_section = Section.objects.create(store=other_store, name='Dry Cleaning')
        Product.objects.create(section=self.other_section, name='Secret', price=D('1.00'))

    def test_requires_store_staff(self):
        for user in (
            User.objects.create_user('cust', password='pw', role=User.Role.CUSTOMER, store=self.store),
            User.objects.create_user('nostore', password='pw'),
        ):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get('/api/products/').status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get('/api/products/').status_code, 401)

    def test_only_own_store_products_are_listed(self):
        names = [p['name'] for p in self.client.get('/api/products/').json()]
        self.assertEqual(sorted(names), ['Shirt', 'Suit'])

    def test_effective_prices_for_price_list(self):
        PriceListItem.objects.create(price_list=self.hotel, product=self.suit, price=D('8.00'))
        rows = {p['name']: p for p in self.client.get(f'/api/products/?price_list={self.hotel.pk}').json()}
        self.assertEqual(rows['Suit']['effective_price'], '8.00')
        self.assertEqual(rows['Suit']['effective_express_price'], '12.00')
        self.assertEqual(rows['Shirt']['effective_price'], '3.00')

    def test_price_list_from_other_store_is_404(self):
        other_list = PriceList.objects.create(store=self.other_section.store, name='Theirs')
        self.assertEqual(self.client.get(f'/api/products/?price_list={other_list.pk}').status_code, 404)

    def test_cannot_create_product_in_other_store_section(self):
        response = self.client.post(
            '/api/products/', {'section': self.other_section.pk, 'name': 'Coat', 'price': '5.00'}, format='json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('section', response.json())

    def test_create_section_attaches_store(self):
        response = self.client.post('/api/sections/', {'name': 'Laundry'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Section.objects.get(pk=response.json()['id']).store, self.store)

    def test_cannot_delete_section_with_products(self):
        self.assertEqual(self.client.delete(f'/api/sections/{self.dry.pk}/').status_code, 409)

    def test_cannot_delete_default_price_list(self):
        self.assertEqual(self.client.delete(f'/api/price-lists/{self.default_list.pk}/').status_code, 409)

    def test_second_default_price_list_rejected(self):
        response = self.client.post('/api/price-lists/', {'name': 'Another', 'is_default': True}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_override_on_default_list_rejected(self):
        response = self.client.post(
            '/api/price-list-items/',
            {'price_list': self.default_list.pk, 'product': self.suit.pk, 'price': '9.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_bulk_update_preview_then_apply(self):
        payload = {
            'products': [self.suit.pk, self.shirt.pk],
            'changes': {'price': {'op': 'increase_amount', 'value': '0.50'}},
        }
        preview = self.client.post('/api/products/bulk-update/', payload, format='json').json()
        self.assertEqual(preview['applied'], False)
        self.assertEqual(preview['product_count'], 2)
        self.suit.refresh_from_db()
        self.assertEqual(self.suit.price, D('10.00'))

        applied = self.client.post('/api/products/bulk-update/', {**payload, 'apply': True}, format='json')
        self.assertEqual(applied.status_code, 200)
        self.suit.refresh_from_db()
        self.assertEqual(self.suit.price, D('10.50'))

    def test_bulk_update_rejects_other_store_products(self):
        secret = Product.objects.get(name='Secret')
        response = self.client.post(
            '/api/products/bulk-update/',
            {'products': [secret.pk], 'changes': {'active': {'value': False}}},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_bulk_update_price_list_field_restriction_is_400(self):
        response = self.client.post(
            '/api/products/bulk-update/',
            {'products': [self.suit.pk], 'price_list': self.hotel.pk,
             'changes': {'cost_price': {'op': 'set', 'value': '1.00'}}},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
