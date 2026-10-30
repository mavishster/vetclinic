"""Склад по умолчанию — «Основной склад» (реализация). Дальше клиника заводит свои."""

from django.conf import settings
from django.db import migrations


def create(apps, schema_editor):
    Warehouse = apps.get_model("inventory", "Warehouse")
    if not Warehouse.objects.exists():
        Warehouse.objects.create(name="Основной склад", kind="sale", node_id=settings.NODE_ID)


class Migration(migrations.Migration):
    dependencies = [("inventory", "0001_stock")]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
