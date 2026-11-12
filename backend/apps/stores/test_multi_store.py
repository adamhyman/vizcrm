"""Behaviour that spans a company's stores: shared catalog and customers, per-store
prices and availability, company-wide order numbers, and choosing a store."""

from decimal import Decimal as D

from django.test import TestCase
from rest_framework.test import APIClient

from apps.catalog.models import PriceList, PriceListItem, Product, Section, StoreProduct
from apps.catalog.services import store_settings, unit_price
from apps.contacts.models import Customer
from apps.orders.services import NewItem, OrderError, create_order

from .testing import create_staff, create_store


class MultiStoreFixture(TestCase):
    def setUp(self):
        self.downtown = create_store('Downtown')
        self.company = self.downtown.company
        self.uptown = create_store('Uptown', company=self.company)
        self.dry = Section.objects.create(company=self.company, name='Dry Cleaning')
        self.suit = Product.objects.create(section=self.dry, name='Suit', price=D('10.00'))
        self.jane = Customer.objects.create(company=self.company, first_name='Jane', phone='310 555 0123')
        self.owner = create_staff('owner', self.downtown, self.uptown)
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def get(self, url, store):
        return self.client.get(url, HTTP_X_STORE=str(store.pk))

    def post(self, url, data, store):
        return self.client.post(url, data, format='json', HTTP_X_STORE=str(store.pk))


class ChoosingAStoreTests(MultiStoreFixture):
    def test_staff_at_several_stores_must_choose(self):
        response = self.client.get('/api/store/')
        self.assertEqual(response.status_code, 403)
        self.assertIn('X-Store', response.json()['detail'])
        self.assertEqual(self.get('/api/store/', self.uptown).json()['name'], 'Uptown')

    def test_staff_at_one_store_need_not_choose(self):
        self.client.force_authenticate(create_staff('clerk', self.uptown))
        self.assertEqual(self.client.get('/api/store/').json()['name'], 'Uptown')
        self.assertEqual(self.get('/api/store/', self.downtown).status_code, 403)

    def test_my_stores(self):
        names = [s['name'] for s in self.client.get('/api/my-stores/').json()]
        self.assertEqual(names, ['Downtown', 'Uptown'])

    def test_other_company_store_is_refused(self):
        elsewhere = create_store('Elsewhere')
        self.assertEqual(self.get('/api/store/', elsewhere).status_code, 403)


class SharedDataTests(MultiStoreFixture):
    def test_catalog_and_customers_are_shared(self):
        self.post('/api/products/', {'section': self.dry.pk, 'name': 'Coat', 'price': '15.00'}, self.downtown)
        names = [p['name'] for p in self.get('/api/products/', self.uptown).json()]
        self.assertEqual(sorted(names), ['Coat', 'Suit'])
        self.assertEqual(self.get('/api/customers/?search=jane', self.uptown).json()['count'], 1)

    def test_other_company_sees_nothing(self):
        elsewhere = create_store('Elsewhere')
        self.client.force_authenticate(create_staff('stranger', elsewhere))
        self.assertEqual(self.client.get('/api/products/').json(), [])
        self.assertEqual(self.client.get('/api/customers/').json()['count'], 0)

    def test_new_customer_records_home_store(self):
        response = self.post('/api/customers/', {'first_name': 'Ana', 'phone': '555 1234'}, self.uptown)
        customer = Customer.objects.get(pk=response.json()['id'])
        self.assertEqual((customer.company, customer.home_store), (self.company, self.uptown))

    def test_store_default_price_list_must_be_the_companys(self):
        theirs = PriceList.objects.create(company=create_store('Elsewhere').company, name='Theirs')
        response = self.client.patch(
            '/api/store/', {'default_price_list': theirs.pk}, format='json', HTTP_X_STORE=str(self.uptown.pk)
        )
        self.assertEqual(response.status_code, 400)


class StorePriceTests(MultiStoreFixture):
    def test_store_price_and_express_fall_back_separately(self):
        StoreProduct.objects.create(store=self.uptown, product=self.suit, price=D('12.00'))
        setting = store_settings(self.uptown)[self.suit.pk]
        prices = unit_price(self.suit, self.uptown, store_setting=setting)
        self.assertEqual((prices.price, prices.express_price), (D('12.00'), D('18.00')))
        setting.express_price = D('20.00')
        self.assertEqual(unit_price(self.suit, self.uptown, store_setting=setting).express_price, D('20.00'))
        self.assertEqual(unit_price(self.suit, self.downtown).price, D('10.00'))

    def test_express_multiplier_is_store_specific(self):
        self.uptown.express_multiplier = D('2.00')
        self.uptown.save()
        self.assertEqual(unit_price(self.suit, self.downtown).express_price, D('15.00'))
        self.assertEqual(unit_price(self.suit, self.uptown).express_price, D('20.00'))
        downtown_order = create_order(self.downtown, self.owner, self.jane, [NewItem(self.suit)], express=True)
        uptown_order = create_order(self.uptown, self.owner, self.jane, [NewItem(self.suit)], express=True)
        self.assertEqual((downtown_order.subtotal, uptown_order.subtotal), (D('15.00'), D('20.00')))
        self.assertEqual(
            self.get('/api/products/', self.uptown).json()[0]['effective_express_price'],
            '20.00',
        )

    def test_orders_use_the_stores_price(self):
        StoreProduct.objects.create(store=self.uptown, product=self.suit, price=D('12.00'))
        self.assertEqual(create_order(self.downtown, self.owner, self.jane, [NewItem(self.suit)]).subtotal, D('10.00'))
        self.assertEqual(create_order(self.uptown, self.owner, self.jane, [NewItem(self.suit)]).subtotal, D('12.00'))

    def test_price_list_wins_over_store_price(self):
        hotel = PriceList.objects.create(company=self.company, name='Hotel')
        PriceListItem.objects.create(price_list=hotel, product=self.suit, price=D('8.00'))
        StoreProduct.objects.create(store=self.uptown, product=self.suit, price=D('12.00'))
        order = create_order(self.uptown, self.owner, self.jane, [NewItem(self.suit)], price_list=hotel)
        self.assertEqual(order.subtotal, D('8.00'))

    def test_products_a_store_does_not_sell(self):
        StoreProduct.objects.create(store=self.uptown, product=self.suit, available=False)
        with self.assertRaises(OrderError):
            create_order(self.uptown, self.owner, self.jane, [NewItem(self.suit)])
        rows = self.get('/api/products/?available_here=true', self.uptown).json()
        self.assertEqual(rows, [])
        rows = self.get('/api/products/', self.downtown).json()
        self.assertEqual([(r['name'], r['available_here']) for r in rows], [('Suit', True)])

    def test_store_products_api(self):
        response = self.post('/api/store-products/', {'product': self.suit.pk, 'price': '11.00'}, self.uptown)
        self.assertEqual(response.status_code, 201, response.json())
        self.assertEqual(self.get('/api/products/', self.uptown).json()[0]['effective_price'], '11.00')
        self.assertEqual(self.get('/api/products/', self.downtown).json()[0]['effective_price'], '10.00')
        again = self.post('/api/store-products/', {'product': self.suit.pk, 'price': '9.00'}, self.uptown)
        self.assertEqual(again.status_code, 400)
        self.assertEqual(self.get('/api/store-products/', self.downtown).json(), [])


class OrderAcrossStoresTests(MultiStoreFixture):
    def test_numbers_count_across_the_company(self):
        numbers = [create_order(store, self.owner, self.jane, [NewItem(self.suit)]).number
                   for store in (self.downtown, self.uptown, self.downtown)]
        self.assertEqual(numbers, [1, 2, 3])
        other = create_store('Elsewhere')
        stranger = Customer.objects.create(company=other.company, first_name='Sam', phone='1')
        self.assertEqual(create_order(other, None, stranger, [NewItem(name='X', price=D('1'))]).number, 1)

    def test_each_store_sees_its_own_board(self):
        create_order(self.downtown, self.owner, self.jane, [NewItem(self.suit)])
        create_order(self.uptown, self.owner, self.jane, [NewItem(self.suit)])
        self.assertEqual([r['number'] for r in self.get('/api/orders/', self.uptown).json()['results']], [2])

    def test_customer_overview_covers_all_stores(self):
        create_order(self.downtown, self.owner, self.jane, [NewItem(self.suit)])
        create_order(self.uptown, self.owner, self.jane, [NewItem(self.suit)])
        body = self.get(f'/api/customers/{self.jane.pk}/overview/', self.uptown).json()
        self.assertEqual((body['total_orders'], body['lifetime_value']), (2, '20.00'))

    def test_walk_in_customer_is_shared(self):
        retail = Section.objects.create(company=self.company, name='Retail', retail=True)
        roller = Product.objects.create(section=retail, name='Lint Roller', price=D('5.00'))
        sales = [create_order(store, self.owner, None, [NewItem(roller)], type='retail')
                 for store in (self.downtown, self.uptown)]
        self.assertEqual(sales[0].customer, sales[1].customer)
