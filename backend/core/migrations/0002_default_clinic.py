"""Создаёт клинику по умолчанию: в первой версии система работает с одной клиникой."""

from django.conf import settings
from django.db import migrations


def create_default_clinic(apps, schema_editor):
    Clinic = apps.get_model("core", "Clinic")
    if not Clinic.objects.exists():
        Clinic.objects.create(name="Клиника", node_id=settings.NODE_ID)


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [migrations.RunPython(create_default_clinic, migrations.RunPython.noop)]
