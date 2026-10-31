"""Кассы по умолчанию: «Наличные» и «Терминал». Дальше клиника заводит свои."""

from django.conf import settings
from django.db import migrations


def create(apps, schema_editor):
    CashRegister = apps.get_model("cash", "CashRegister")
    if not CashRegister.objects.exists():
        CashRegister.objects.create(name="Наличные", kind="cash", node_id=settings.NODE_ID)
        CashRegister.objects.create(name="Терминал", kind="cashless", node_id=settings.NODE_ID)


class Migration(migrations.Migration):
    dependencies = [("cash", "0001_cash")]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
