from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import PriceList
from apps.stores.models import Store

from .models import BusinessAccount, Customer, CustomerGroup
from .services import search_customers


class ContactsFixture(TestCase):
    def setUp(self):
        self.store = Store.objects.create(name='Main St')
        self.jane = Customer.objects.create(
            store=self.store, first_name='Jane', last_name='Smith', phone='(310) 555-0123', email='jane@example.com'
        )
        self.john = Customer.objects.create(store=self.store, first_name='John', last_name='Smithers', phone='818 555 9876')
        self.bob = Customer.objects.create(store=self.store, first_name='Bob', phone='+1 213 555 0100')


class SearchTests(ContactsFixture):
    def search(self, text):
        return sorted(c.first_name for c in search_customers(Customer.objects.all(), text))

    def test_phone_digits_kept_in_sync(self):
        self.assertEqual(self.jane.phone_digits, '3105550123')
        self.jane.phone = '424-555-0000'
        self.jane.save(update_fields=['phone'])
        self.jane.refresh_from_db()
        self.assertEqual(self.jane.phone_digits, '4245550000')

    def test_phone_search_ignores_formatting(self):
        self.assertEqual(self.search('310-555'), ['Jane'])
        self.assertEqual(self.search('(818) 555'), ['John'])
        self.assertEqual(self.search('0100'), ['Bob'])

    def test_phone_search_matches_any_part(self):
        self.assertEqual(self.search('555'), ['Bob', 'Jane', 'John'])

    def test_name_search(self):
        self.assertEqual(self.search('smith'), ['Jane', 'John'])
        self.assertEqual(self.search('jane smith'), ['Jane'])

    def test_email_search(self):
        self.assertEqual(self.search('jane@'), ['Jane'])

    def test_short_number_searches_names(self):
        # Two digits could be part of a name / email search, not a phone search.
        self.assertEqual(self.search('55'), [])


class EffectivePriceListTests(ContactsFixture):
    def test_customer_then_business_then_none(self):
        hotel_list = PriceList.objects.create(store=self.store, name='Hotel')
        vip_list = PriceList.objects.create(store=self.store, name='VIP')
        self.jane.business = BusinessAccount.objects.create(store=self.store, name='Hotel', price_list=hotel_list)
        self.assertEqual(self.jane.effective_price_list(), hotel_list)
        self.jane.price_list = vip_list
        self.assertEqual(self.jane.effective_price_list(), vip_list)
        self.assertIsNone(self.bob.effective_price_list())


class CustomerApiTests(ContactsFixture):
    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_user('alex', password='pw', store=self.store)
        self.client = APIClient()
        self.client.force_authenticate(self.staff)

        self.other_store = Store.objects.create(name='Elsewhere')
        Customer.objects.create(store=self.other_store, first_name='Secret', phone='310 555 0199')

    def test_requires_store_staff(self):
        self.client.force_authenticate(User.objects.create_user('cust', password='pw', role=User.Role.CUSTOMER))
        self.assertEqual(self.client.get('/api/customers/').status_code, 403)

    def test_only_own_store_customers_are_listed(self):
        body = self.client.get('/api/customers/?search=310').json()
        self.assertEqual([c['full_name'] for c in body['results']], ['Jane Smith'])

    def test_list_is_paginated(self):
        body = self.client.get('/api/customers/?page_size=2').json()
        self.assertEqual(body['count'], 3)
        self.assertEqual(len(body['results']), 2)

    def test_create_with_address(self):
        response = self.client.post('/api/customers/', {
            'first_name': 'Ana', 'phone': '555 1234',
            'street_address': '1 Main St', 'city': 'Los Angeles', 'driver_instructions': 'Gate 42',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.json())
        customer = Customer.objects.get(pk=response.json()['id'])
        self.assertEqual(customer.store, self.store)
        self.assertEqual((customer.street_address, customer.driver_instructions), ('1 Main St', 'Gate 42'))

    def test_update_address(self):
        response = self.client.patch(
            f'/api/customers/{self.jane.pk}/', {'street_address': '2 Elm St', 'unit': '4B'}, format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.jane.refresh_from_db()
        self.assertEqual((self.jane.street_address, self.jane.unit), ('2 Elm St', '4B'))

    def test_phone_required_by_default(self):
        response = self.client.post('/api/customers/', {'first_name': 'Ana'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('phone', response.json())

    def test_required_fields_follow_store_setting(self):
        self.store.customer_required_fields = ['email', 'address']
        self.store.save()
        response = self.client.post('/api/customers/', {'first_name': 'Ana'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()), {'email', 'street_address'})

        self.store.customer_required_fields = []
        self.store.save()
        self.assertEqual(self.client.post('/api/customers/', {'first_name': 'Ana'}, format='json').status_code, 201)

    def test_cannot_clear_required_phone(self):
        response = self.client.patch(f'/api/customers/{self.jane.pk}/', {'phone': ''}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_phone_without_digits_rejected(self):
        response = self.client.post('/api/customers/', {'first_name': 'Ana', 'phone': 'call me'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_cannot_use_other_store_price_list_or_group(self):
        other_list = PriceList.objects.create(store=self.other_store, name='Theirs')
        other_group = CustomerGroup.objects.create(store=self.other_store, name='Theirs')
        response = self.client.patch(
            f'/api/customers/{self.jane.pk}/', {'price_list': other_list.pk, 'groups': [other_group.pk]}, format='json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()), {'price_list', 'groups'})

    def test_business_search(self):
        BusinessAccount.objects.create(store=self.store, name='Grand Hotel', phone='310 555 0000')
        BusinessAccount.objects.create(store=self.store, name='Cafe')
        names = [b['name'] for b in self.client.get('/api/business-accounts/?search=hotel').json()]
        self.assertEqual(names, ['Grand Hotel'])
