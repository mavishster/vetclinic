"""Профили сотрудников для уже существующих учётных записей."""

from django.conf import settings
from django.db import migrations


def create(apps, schema_editor):
    User = apps.get_model("core", "User")
    Employee = apps.get_model("staff", "Employee")
    for user in User.objects.filter(employee__isnull=True):
        Employee.objects.create(user=user, node_id=settings.NODE_ID)


class Migration(migrations.Migration):
    dependencies = [("staff", "0002_initial_directories"), ("core", "0009_initial_file_categories")]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
