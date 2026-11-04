"""Начальные отделения. Клиника может добавить свои."""

from django.conf import settings
from django.db import migrations

NAMES = ["Хирургия", "Стационар", "Терапия", "Приёмная"]


def create(apps, schema_editor):
    Department = apps.get_model("inventory", "Department")
    for name in NAMES:
        Department.objects.get_or_create(name=name, defaults={"node_id": settings.NODE_ID})


class Migration(migrations.Migration):
    dependencies = [("inventory", "0010_departments")]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
