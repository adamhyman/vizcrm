import datetime
from decimal import Decimal as D

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.catalog.models import PriceList, Product, Section, Upcharge
from apps.stores.models import BusinessHours, Station, Store, TaxRate

# (section, [(product, price, pieces_per_unit, pricing_unit)])
CATALOG = [
    ('Dry Cleaning', [
        ('Shirt', '3.25', 1, 'piece'), ('Blouse', '6.00', 1, 'piece'), ('Trousers', '6.50', 1, 'piece'),
        ('Skirt', '6.50', 1, 'piece'), ('Dress', '12.00', 1, 'piece'), ('Jacket', '8.50', 1, 'piece'),
        ('Two-Piece Suit', '14.00', 2, 'piece'), ('Three-Piece Suit', '18.00', 3, 'piece'),
        ('Coat', '16.00', 1, 'piece'), ('Sweater', '7.00', 1, 'piece'), ('Tie', '4.50', 1, 'piece'),
    ]),
    ('Laundry', [
        ('Wash & Fold', '2.10', 1, 'weight'), ('Comforter', '28.00', 1, 'piece'),
        ('Duvet Cover', '14.00', 1, 'piece'), ('Pillowcase', '2.50', 1, 'piece'),
        ('Tablecloth', '9.00', 1, 'piece'), ('Bath Towel', '3.00', 1, 'piece'),
    ]),
    ('Pressed Only', [
        ('Shirt (press)', '2.50', 1, 'piece'), ('Trousers (press)', '4.00', 1, 'piece'),
        ('Dress (press)', '7.00', 1, 'piece'),
    ]),
    ('Alterations', [
        ('Hem Trousers', '15.00', 1, 'piece'), ('Take In Waist', '20.00', 1, 'piece'),
        ('Shorten Sleeves', '22.00', 1, 'piece'), ('Replace Zipper', '18.00', 1, 'piece'),
    ]),
    ('Repairs', [
        ('Sew Button', '2.00', 1, 'piece'), ('Patch Hole', '10.00', 1, 'piece'),
        ('Heel Tips', '12.00', 1, 'piece'),
    ]),
    ('Retail', [
        ('Lint Roller', '5.00', 1, 'piece'), ('Garment Bag', '8.00', 1, 'piece'),
    ]),
]


class Command(BaseCommand):
    help = 'Create (or top up) a demo store with sections, products, prices and upcharges.'

    def add_arguments(self, parser):
        parser.add_argument('--store', default='VIZCRM Demo', help='Store name to create or reuse.')
        parser.add_argument('--user', help='Username of an existing user to attach to the store as staff.')

    @transaction.atomic
    def handle(self, *args, store, user, **options):
        store_obj, created = Store.objects.get_or_create(
            name=store,
            defaults={
                'phone': '(555) 010-0100', 'city': 'Los Angeles', 'region': 'CA',
                'turnaround_excluded_weekdays': [6],  # Sundays don't count towards turnaround
            },
        )
        if not store_obj.business_hours.exists():
            for weekday in range(6):  # Monday–Saturday 7am–7pm; closed Sunday
                BusinessHours.objects.create(
                    store=store_obj, weekday=weekday, starts_at=datetime.time(7), ends_at=datetime.time(19)
                )
        Station.objects.get_or_create(store=store_obj, name='Station 1')
        TaxRate.objects.get_or_create(store=store_obj, position=1, defaults={'name': 'Sales Tax', 'rate': D('9.5')})
        PriceList.objects.get_or_create(store=store_obj, is_default=True, defaults={'name': 'Standard'})
        PriceList.objects.get_or_create(store=store_obj, name='Business Accounts')

        product_count = 0
        for position, (section_name, products) in enumerate(CATALOG, start=1):
            section, _ = Section.objects.get_or_create(
                store=store_obj, name=section_name, defaults={'position': position}
            )
            for product_position, (name, price, pieces, unit) in enumerate(products, start=1):
                _, made = Product.objects.get_or_create(
                    section=section, name=name,
                    defaults={'price': D(price), 'pieces_per_unit': pieces, 'pricing_unit': unit,
                              'position': product_position},
                )
                product_count += made

        stain, _ = Upcharge.objects.get_or_create(
            store=store_obj, name='Stain Treatment', defaults={'kind': 'fixed', 'amount': D('3.00')}
        )
        Upcharge.objects.get_or_create(
            store=store_obj, name='Delicate Fabric', defaults={'kind': 'percent', 'amount': D('25')}
        )
        stain.products.add(*Product.objects.filter(section__store=store_obj, section__name='Dry Cleaning'))

        if user:
            try:
                staff = User.objects.get(username=user)
            except User.DoesNotExist as exc:
                raise CommandError(f'No user named {user!r}. Create one with createsuperuser first.') from exc
            staff.store, staff.role = store_obj, User.Role.STAFF
            staff.save(update_fields=['store', 'role'])
            self.stdout.write(f'Attached {user} to {store_obj}.')

        verb = 'Created' if created else 'Updated'
        self.stdout.write(self.style.SUCCESS(f'{verb} store "{store_obj}" ({product_count} new products).'))
