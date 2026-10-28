"""Начальный список видов животных. Дальше справочник пополняет сама клиника."""

from django.conf import settings
from django.db import migrations

SPECIES = ["Кошки", "Собаки", "Грызуны", "Кролики", "Хорьки", "Птицы", "Рептилии", "Рыбы"]


def create_species(apps, schema_editor):
    Species = apps.get_model("clients", "Species")
    for name in SPECIES:
        Species.objects.get_or_create(name=name, defaults={"node_id": settings.NODE_ID})


class Migration(migrations.Migration):
    dependencies = [("clients", "0001_initial")]

    operations = [migrations.RunPython(create_species, migrations.RunPython.noop)]
