"""Give every existing store its own company and move store-wide data to it.

Catalog, customers and staff move from the store to its company; orders get the
company too. Each company starts with a single store, so existing order numbers
are already unique company-wide and stay as they are.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    Company = apps.get_model('stores', 'Company')
    Store = apps.get_model('stores', 'Store')
    User = apps.get_model('accounts', 'User')

    for store in Store.objects.filter(company__isnull=True):
        store.company = Company.objects.create(name=store.name, express_multiplier=store.express_multiplier)
        store.save(update_fields=['company'])

    for app_label, model_name in [
        ('catalog', 'Section'), ('catalog', 'PriceList'), ('catalog', 'Upcharge'),
        ('contacts', 'Customer'), ('contacts', 'BusinessAccount'), ('contacts', 'CustomerGroup'),
        ('orders', 'Order'),
    ]:
        model = apps.get_model(app_label, model_name)
        for obj in model.objects.select_related('store').filter(company__isnull=True):
            obj.company_id = obj.store.company_id
            if model_name == 'Customer':
                obj.home_store_id = obj.store_id
            obj.save()

    for user in User.objects.exclude(store=None):
        user.company_id = user.store.company_id
        user.save(update_fields=['company'])
        user.stores.add(user.store)


class Migration(migrations.Migration):

    dependencies = [
        ('stores', '0009_company'),
        ('accounts', '0003_user_company_stores'),
        ('catalog', '0004_company_fields'),
        ('contacts', '0005_company_fields'),
        ('orders', '0005_order_company'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
