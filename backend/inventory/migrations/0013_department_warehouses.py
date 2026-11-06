"""У каждого существующего отделения — свой склад (тип «отделение», ADR-024).

Новым отделениям склад создаётся сам при первой операции (inventory.departments).
"""

from django.conf import settings
from django.db import migrations


def create(apps, schema_editor):
    Department = apps.get_model("inventory", "Department")
    Warehouse = apps.get_model("inventory", "Warehouse")
    for department in Department.objects.filter(warehouse__isnull=True, is_deleted=False):
        name = f"Отделение «{department.name}»"
        warehouse = Warehouse.objects.filter(name=name, is_deleted=False).first()
        if warehouse is None:
            warehouse = Warehouse.objects.create(
                name=name, kind="department", node_id=settings.NODE_ID
            )
        department.warehouse = warehouse
        department.save(update_fields=["warehouse"])


class Migration(migrations.Migration):
    dependencies = [("inventory", "0012_department_stock")]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
