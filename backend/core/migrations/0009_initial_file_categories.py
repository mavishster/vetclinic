"""Начальные категории файлов. Дальше клиника меняет список сама."""

from django.conf import settings
from django.db import migrations

CATEGORIES = ["Общий", "Договор", "Анализы", "Рентген", "УЗИ", "Фото", "Выписки и заключения"]


def create(apps, schema_editor):
    FileCategory = apps.get_model("core", "FileCategory")
    for name in CATEGORIES:
        FileCategory.objects.get_or_create(name=name, defaults={"node_id": settings.NODE_ID})


class Migration(migrations.Migration):
    dependencies = [("core", "0008_attachments")]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
