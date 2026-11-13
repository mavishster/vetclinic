"""Клиентам без типа ставится «Обычный» — тип по умолчанию (новым — при сохранении)."""

from django.conf import settings
from django.db import migrations


def fill(apps, schema_editor):
    ClientType = apps.get_model("clients", "ClientType")
    Client = apps.get_model("clients", "Client")
    usual = ClientType.objects.filter(name__iexact="Обычный").first()
    if usual is None:
        usual = ClientType.objects.create(name="Обычный", node_id=settings.NODE_ID)
    Client.objects.filter(client_type__isnull=True, is_guest=False).update(client_type=usual)


class Migration(migrations.Migration):
    dependencies = [("clients", "0016_contracts_from_signed")]

    operations = [migrations.RunPython(fill, migrations.RunPython.noop)]
