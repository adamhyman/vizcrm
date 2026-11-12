import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.stores.testing import create_staff, create_store

from .models import BusinessHours, ClosedDate, Store, TaxRate
from .services import due_at, ip_allowed

LA = ZoneInfo('America/Los_Angeles')


def la(*args):
    return datetime.datetime(*args, tzinfo=LA)


class DueDateTests(TestCase):
    def setUp(self):
        # 2026-11-02 is a Monday.
        self.store = create_store(name='Main St', turnaround_days=2, ready_time=datetime.time(17))

    def test_counts_turnaround_days_at_ready_time(self):
        self.assertEqual(due_at(self.store, la(2026, 11, 2, 9)), la(2026, 11, 4, 17))

    def test_returns_store_local_time_for_utc_input(self):
        dropped = datetime.datetime(2026, 11, 2, 17, tzinfo=datetime.UTC)  # 09:00 in LA
        due = due_at(self.store, dropped)
        self.assertEqual(due, la(2026, 11, 4, 17))
        self.assertEqual(due.tzinfo, LA)

    def test_skips_excluded_weekdays(self):
        self.store.turnaround_excluded_weekdays = [5, 6]
        # Thursday + 2 counted days skips Sat/Sun → Monday.
        self.assertEqual(due_at(self.store, la(2026, 11, 5, 9)), la(2026, 11, 9, 17))

    def test_skips_closed_dates(self):
        ClosedDate.objects.create(store=self.store, date=datetime.date(2026, 11, 3))
        self.assertEqual(due_at(self.store, la(2026, 11, 2, 9)), la(2026, 11, 5, 17))

    def test_express_turnaround(self):
        self.store.express_turnaround_days = 1
        self.assertEqual(due_at(self.store, la(2026, 11, 2, 9), express=True), la(2026, 11, 3, 17))

    def test_express_ready_time(self):
        self.store.express_turnaround_days = 1
        self.store.express_ready_time = datetime.time(12)
        self.assertEqual(due_at(self.store, la(2026, 11, 2, 9), express=True), la(2026, 11, 3, 12))
        # Normal orders keep the normal ready time.
        self.assertEqual(due_at(self.store, la(2026, 11, 2, 9)), la(2026, 11, 4, 17))

    def test_same_day_express_without_cutoff_uses_express_ready_time(self):
        self.store.express_turnaround_days = 0
        self.store.express_ready_time = datetime.time(12)
        self.assertEqual(due_at(self.store, la(2026, 11, 2, 9), express=True), la(2026, 11, 2, 12))
        self.assertEqual(due_at(self.store, la(2026, 11, 2, 13), express=True), la(2026, 11, 3, 12))

    def test_express_without_own_turnaround_uses_normal(self):
        self.assertEqual(due_at(self.store, la(2026, 11, 2, 9), express=True), la(2026, 11, 4, 17))

    def test_extra_days(self):
        self.assertEqual(due_at(self.store, la(2026, 11, 2, 9), extra_days=1), la(2026, 11, 5, 17))

    def test_same_day_before_ready_time(self):
        self.store.turnaround_days = 0
        self.assertEqual(due_at(self.store, la(2026, 11, 2, 9)), la(2026, 11, 2, 17))

    def test_same_day_after_ready_time_rolls_to_next_counting_day(self):
        self.store.turnaround_days = 0
        self.store.turnaround_excluded_weekdays = [1]  # Tuesday
        self.assertEqual(due_at(self.store, la(2026, 11, 2, 18)), la(2026, 11, 4, 17))

    def test_same_day_on_closed_day_rolls_forward(self):
        self.store.turnaround_days = 0
        self.store.turnaround_excluded_weekdays = [6]
        self.assertEqual(due_at(self.store, la(2026, 11, 8, 9)), la(2026, 11, 9, 17))  # Sunday → Monday

    def test_before_cutoff_has_normal_turnaround(self):
        self.store.cutoff_time = datetime.time(14)
        self.assertEqual(due_at(self.store, la(2026, 11, 2, 13, 59)), la(2026, 11, 4, 17))

    def test_at_or_after_cutoff_adds_a_day(self):
        self.store.cutoff_time = datetime.time(14)
        self.assertEqual(due_at(self.store, la(2026, 11, 2, 14)), la(2026, 11, 5, 17))
        self.assertEqual(due_at(self.store, la(2026, 11, 2, 18)), la(2026, 11, 5, 17))

    def test_cutoff_extra_day_skips_excluded_weekdays(self):
        self.store.cutoff_time = datetime.time(14)
        self.store.turnaround_excluded_weekdays = [5, 6]
        # Wednesday after cutoff: 3 counted days → Thu, Fri, Mon.
        self.assertEqual(due_at(self.store, la(2026, 11, 4, 15)), la(2026, 11, 9, 17))

    def test_same_day_uses_cutoff_instead_of_ready_time(self):
        self.store.turnaround_days = 0
        self.store.cutoff_time = datetime.time(10)
        self.assertEqual(due_at(self.store, la(2026, 11, 2, 9)), la(2026, 11, 2, 17))
        self.assertEqual(due_at(self.store, la(2026, 11, 2, 11)), la(2026, 11, 3, 17))

    def test_past_closed_dates_do_not_matter(self):
        ClosedDate.objects.create(store=self.store, date=datetime.date(2026, 10, 1))
        self.assertEqual(due_at(self.store, la(2026, 11, 2, 9)), la(2026, 11, 4, 17))


class IpAllowListTests(TestCase):
    def test_empty_allows_everyone(self):
        self.assertTrue(ip_allowed(Store(name='x'), '203.0.113.9'))

    def test_addresses_and_ranges(self):
        store = Store(name='x', allowed_ips='203.0.113.9\n198.51.100.0/24')
        self.assertTrue(ip_allowed(store, '203.0.113.9'))
        self.assertTrue(ip_allowed(store, '198.51.100.77'))
        self.assertFalse(ip_allowed(store, '203.0.113.10'))
        self.assertFalse(ip_allowed(store, 'not-an-ip'))


class StoreApiTests(TestCase):
    def setUp(self):
        self.store = create_store(name='Main St')
        self.user = create_staff('alex', self.store)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_current_store_read_and_update(self):
        self.assertEqual(self.client.get('/api/store/').json()['name'], 'Main St')
        response = self.client.patch(
            '/api/store/', {'turnaround_days': 3, 'city': 'Pasadena', 'express_multiplier': '1.75'}, format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.store.refresh_from_db()
        self.assertEqual(
            (self.store.turnaround_days, self.store.city, self.store.express_multiplier),
            (3, 'Pasadena', Decimal('1.75')),
        )

    def test_current_company_contact_read_and_update(self):
        response = self.client.get('/api/company/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {field: response.json()[field] for field in ('primary_contact', 'phone', 'email', 'website')},
            {'primary_contact': '', 'phone': '', 'email': '', 'website': ''},
        )
        self.assertNotIn('express_multiplier', response.json())

        response = self.client.patch(
            '/api/company/',
            {
                'primary_contact': 'Alex Smith',
                'phone': '555-0100',
                'email': 'alex@example.com',
                'website': 'https://example.com',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.store.company.refresh_from_db()
        self.assertEqual(
            (
                self.store.company.primary_contact,
                self.store.company.phone,
                self.store.company.email,
                self.store.company.website,
            ),
            ('Alex Smith', '555-0100', 'alex@example.com', 'https://example.com'),
        )

    def test_current_company_rejects_invalid_contact_email(self):
        response = self.client.patch('/api/company/', {'email': 'not-an-email'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('email', response.json())

    def test_store_field_validation(self):
        for field, bad in [
            ('timezone', 'Mars/Base'),
            ('brand_color', 'blue'),
            ('turnaround_excluded_weekdays', [7]),
            ('turnaround_excluded_weekdays', [0, 1, 2, 3, 4, 5, 6]),
            ('allowed_ips', '10.0.0.0/8\nnonsense'),
            ('latitude', '91'),
        ]:
            response = self.client.patch('/api/store/', {field: bad}, format='json')
            self.assertEqual(response.status_code, 400, (field, bad))
            self.assertIn(field, response.json())

    def test_tax_position_must_be_unique_per_store(self):
        TaxRate.objects.create(store=self.store, position=1, name='Sales Tax', rate='9.5')
        response = self.client.post('/api/store/tax-rates/', {'position': 1, 'name': 'City', 'rate': '1'}, format='json')
        self.assertEqual(response.status_code, 400)
        response = self.client.post('/api/store/tax-rates/', {'position': 2, 'name': 'City', 'rate': '1'}, format='json')
        self.assertEqual(response.status_code, 201)

    def test_tax_position_limited_to_three(self):
        response = self.client.post('/api/store/tax-rates/', {'position': 4, 'name': 'Extra', 'rate': '1'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_business_hours(self):
        url = '/api/store/business-hours/'
        self.assertEqual(self.client.post(url, {'weekday': 0, 'starts_at': '08:00', 'ends_at': '12:00'}).status_code, 201)
        # Lunch break: a second period the same day is fine…
        self.assertEqual(self.client.post(url, {'weekday': 0, 'starts_at': '13:00', 'ends_at': '18:00'}).status_code, 201)
        # …but overlapping or backwards periods are not.
        self.assertEqual(self.client.post(url, {'weekday': 0, 'starts_at': '11:00', 'ends_at': '14:00'}).status_code, 400)
        self.assertEqual(self.client.post(url, {'weekday': 1, 'starts_at': '18:00', 'ends_at': '08:00'}).status_code, 400)
        self.assertEqual(BusinessHours.objects.filter(store=self.store).count(), 2)

    def test_shifts(self):
        response = self.client.post(
            '/api/store/shifts/', {'name': 'Morning', 'weekday': 2, 'starts_at': '07:00', 'ends_at': '15:00'}
        )
        self.assertEqual(response.status_code, 201)

    def test_closed_dates_list_upcoming_by_default(self):
        ClosedDate.objects.create(store=self.store, date=datetime.date(2020, 1, 1), reason='Old')
        ClosedDate.objects.create(store=self.store, date=datetime.date(2099, 12, 25), reason='Future')
        reasons = [d['reason'] for d in self.client.get('/api/store/closed-dates/').json()]
        self.assertEqual(reasons, ['Future'])
        all_reasons = [d['reason'] for d in self.client.get('/api/store/closed-dates/?all=true').json()]
        self.assertEqual(all_reasons, ['Old', 'Future'])

    def test_duplicate_closed_date_rejected(self):
        ClosedDate.objects.create(store=self.store, date=datetime.date(2099, 12, 25))
        response = self.client.post('/api/store/closed-dates/', {'date': '2099-12-25'})
        self.assertEqual(response.status_code, 400)

    def test_due_date_preview(self):
        response = self.client.get(
            '/api/store/due-date/', {'dropped_off_at': '2026-11-02T09:00:00-08:00', 'express': 'false'}
        )
        self.assertEqual(response.json(), {'due_at': '2026-11-04T17:00:00-08:00'})

    def test_ip_restriction(self):
        self.store.allowed_ips = '203.0.113.9'
        self.store.save()
        self.assertEqual(self.client.get('/api/store/', REMOTE_ADDR='198.51.100.1').status_code, 403)
        self.assertEqual(self.client.get('/api/store/', REMOTE_ADDR='203.0.113.9').status_code, 200)

    def test_superuser_bypasses_ip_restriction(self):
        self.store.allowed_ips = '203.0.113.9'
        self.store.save()
        self.user.is_superuser = True
        self.user.save()
        self.assertEqual(self.client.get('/api/store/', REMOTE_ADDR='198.51.100.1').status_code, 200)


class StoreTimezoneAdminTests(TestCase):
    def setUp(self):
        self.store = create_store(name='Main St', timezone='America/New_York')
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw', company=self.store.company)
        self.client.force_login(self.user)

    def test_admin_runs_in_store_timezone(self):
        html = self.client.get(f'/admin/stores/store/{self.store.pk}/change/').content.decode()
        offset = int(html.split('data-admin-utc-offset="')[1].split('"')[0])
        self.assertIn(offset, (-5 * 3600, -4 * 3600))  # EST / EDT
        self.assertIn("In the store's timezone (America/New York).", html)

    def test_admin_timezone_is_a_dropdown(self):
        html = self.client.get(f'/admin/stores/store/{self.store.pk}/change/').content.decode()
        self.assertIn('<select name="timezone"', html)
        self.assertIn('<option value="America/New_York" selected>', html)

    def test_company_admin_has_a_contact_section(self):
        html = self.client.get(f'/admin/stores/company/{self.store.company_id}/change/').content.decode()
        self.assertIn('Contact', html)
        for field in ('primary_contact', 'phone', 'email', 'website'):
            self.assertIn(f'name="{field}"', html)
        self.assertNotIn('name="express_multiplier"', html)

    def test_store_admin_has_express_multiplier(self):
        html = self.client.get(f'/admin/stores/store/{self.store.pk}/change/').content.decode()
        self.assertIn('name="express_multiplier"', html)

    def test_users_without_store_stay_on_utc(self):
        self.user.company = None
        self.user.save()
        html = self.client.get('/admin/').content.decode()
        self.assertIn('data-admin-utc-offset="0"', html)


class AddStoreAdminTests(TestCase):
    def setUp(self):
        self.store = create_store(name='Main St')
        self.client.force_login(
            User.objects.create_superuser('boss', 'b@example.com', 'pw', company=self.store.company)
        )

    def test_add_page_opens_with_default_timezone(self):
        response = self.client.get('/admin/stores/store/add/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('<option value="America/Los_Angeles" selected>', response.content.decode())

    def test_add_a_second_store_to_the_company(self):
        from .admin import StoreForm

        initial = StoreForm().initial
        data = {k: v for k, v in initial.items() if v is not None and k != 'logo'}
        data.update({'company': self.store.company_id, 'name': 'Uptown', 'country': 'US', 'language': 'en',
                     'currency': 'USD', 'weight_unit': 'lb', 'distance_unit': 'imperial', 'tax_mode': 'exclusive',
                     'turnaround_days': 2, 'express_multiplier': '1.50', 'rack_slot_count': 50,
                     'detailing_orders': 'quick_drop',
                     'first_order_discount_percent': '0', 'minimum_order_amount': '0',
                     'minimum_express_order_amount': '0'})
        form = StoreForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().company, self.store.company)


class StoreAdminFormTests(TestCase):
    def setUp(self):
        self.store = create_store(name='Main St')

    def form_data(self, **overrides):
        from .admin import StoreForm

        form = StoreForm(instance=self.store)
        data = {k: v for k, v in form.initial.items() if v is not None and k != 'logo'}
        data.update({'ready_time': str(self.store.ready_time), **overrides})
        return StoreForm(data=data, instance=self.store)

    def test_ready_time_is_an_hourly_dropdown(self):
        from .admin import HOUR_CHOICES, StoreForm

        labels = [label for _, label in HOUR_CHOICES]
        self.assertEqual(labels[:3] + labels[11:14] + labels[-1:], ['12am', '1am', '2am', '11am', '12pm', '1pm', '11pm'])
        self.assertIn('<option value="17:00:00" selected>5pm</option>', str(StoreForm(instance=self.store)['ready_time']))

    def test_ready_time_saves(self):
        form = self.form_data(ready_time='08:00:00')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().ready_time, datetime.time(8))

    def test_off_the_hour_ready_time_is_kept_as_an_option(self):
        from .admin import StoreForm

        self.store.ready_time = datetime.time(17, 30)
        self.assertIn('5:30pm', str(StoreForm(instance=self.store)['ready_time']))

    def test_cutoff_time_dropdown(self):
        from .admin import StoreForm

        html = str(StoreForm(instance=self.store)['cutoff_time'])
        self.assertIn('<option value="" selected>No cutoff</option>', html)
        self.assertIn('<option value="14:00:00">2pm</option>', html)

    def test_cutoff_time_saves_and_clears(self):
        form = self.form_data(cutoff_time='14:00:00')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().cutoff_time, datetime.time(14))
        form = self.form_data(cutoff_time='')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.save().cutoff_time)

    def test_express_ready_time_dropdown(self):
        from .admin import StoreForm

        html = str(StoreForm(instance=self.store)['express_ready_time'])
        self.assertIn('<option value="" selected>Same as ready time</option>', html)
        form = self.form_data(express_ready_time='12:00:00')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().express_ready_time, datetime.time(12))

    def test_exclude_days_multi_select(self):
        form = self.form_data(turnaround_excluded_weekdays=['5', '6'])
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().turnaround_excluded_weekdays, [5, 6])

    def test_exclude_days_cannot_be_every_day(self):
        form = self.form_data(turnaround_excluded_weekdays=[str(d) for d in range(7)])
        self.assertFalse(form.is_valid())
        self.assertIn('turnaround_excluded_weekdays', form.errors)
