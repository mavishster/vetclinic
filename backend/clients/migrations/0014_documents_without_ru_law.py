"""Договор на подпись — без ссылки на ГК РФ (клиника в Кыргызстане).

Меняется только начальный текст, если клиника его ещё не правила.
"""

from django.db import migrations

OLD = "равнозначна собственноручной подписи на бумаге (ст. 160 ГК РФ)."
NEW = "равнозначна собственноручной подписи на бумаге."


def update(apps, schema_editor):
    PrintTemplate = apps.get_model("core", "PrintTemplate")
    for template in PrintTemplate.objects.filter(kind="client_document", body__contains=OLD):
        template.body = template.body.replace(OLD, NEW)
        template.save(update_fields=["body"])


class Migration(migrations.Migration):
    dependencies = [("clients", "0013_photo_request")]

    operations = [migrations.RunPython(update, migrations.RunPython.noop)]
