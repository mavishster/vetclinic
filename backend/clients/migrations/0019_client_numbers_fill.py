"""Номера уже заведённым клиентам.

Перенесённые из VetManager получают его номер (как в его списке клиентов), остальные —
следующие по порядку создания. Таблица переноса читается напрямую, если она есть, чтобы
не связывать миграции клиентов с модулем переноса.
"""

from django.conf import settings
from django.db import migrations

COUNTER = "client_number"


def fill(apps, schema_editor):
    Client = apps.get_model("clients", "Client")
    Counter = apps.get_model("core", "DocumentCounter")
    connection = schema_editor.connection
    taken: set[int] = set()
    if "vetmanager_imported" in connection.introspection.table_names():
        with connection.cursor() as cursor:
            cursor.execute("SELECT external_id, target_id FROM vetmanager_imported WHERE kind = 'client'")
            links = cursor.fetchall()
        for external_id, target_id in links:
            number = int(external_id) if str(external_id).isdigit() else 0
            if 0 < number < 2**31 and number not in taken:
                Client.objects.filter(pk=target_id, number__isnull=True).update(number=number)
                taken.add(number)
    last = max(taken, default=0)
    for client in Client.objects.filter(number__isnull=True).order_by("created_at", "pk"):
        last += 1
        client.number = last
        client.save(update_fields=["number"])
    counter, _ = Counter.objects.get_or_create(
        doc_type=COUNTER, node_id=settings.NODE_ID, defaults={"last_number": 0}
    )
    counter.last_number = max(counter.last_number, last)
    counter.save(update_fields=["last_number"])


class Migration(migrations.Migration):
    dependencies = [
        ("clients", "0018_client_number"),
        ("core", "0014_alter_documentcounter_options"),
    ]

    operations = [migrations.RunPython(fill, migrations.RunPython.noop)]
