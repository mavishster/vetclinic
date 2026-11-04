"""Основной склад — хранение, оперативный — продажа (по счетам списывается с него).

Черновики счетов, у которых стоит основной склад, переводятся на оперативный.
Выполненные счета не меняются.
"""

from django.conf import settings
from django.db import migrations


def create(apps, schema_editor):
    Warehouse = apps.get_model("inventory", "Warehouse")
    Invoice = apps.get_model("billing", "Invoice")
    main = Warehouse.objects.filter(name="Основной склад").first()
    operative, _ = Warehouse.objects.get_or_create(
        name="Оперативный склад", defaults={"kind": "sale", "node_id": settings.NODE_ID}
    )
    if main is not None and main.kind == "sale":
        main.kind = "storage"
        main.save(update_fields=["kind"])
        Invoice.objects.filter(status="draft", warehouse=main).update(warehouse=operative)


class Migration(migrations.Migration):
    dependencies = [("inventory", "0008_warehouse_access"), ("billing", "0009_alter_invoiceline_options_and_more")]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
