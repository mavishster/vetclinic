"""Порода «Метис» для кошек и собак и частые окрасы — для быстрого заполнения."""

from django.conf import settings
from django.db import migrations

COLORS = ["Белый", "Чёрный", "Рыжий", "Серый", "Трёхцветный", "Черепаховый", "Полосатый", "Пятнистый"]


def create(apps, schema_editor):
    Species = apps.get_model("clients", "Species")
    Breed = apps.get_model("clients", "Breed")
    Color = apps.get_model("clients", "Color")
    node = {"node_id": settings.NODE_ID}
    for species_name in ("Кошки", "Собаки"):
        species = Species.objects.filter(name=species_name).first()
        if species:
            Breed.objects.get_or_create(name="Метис", species=species, defaults=node)
    for name in COLORS:
        Color.objects.get_or_create(name=name, defaults=node)


class Migration(migrations.Migration):
    dependencies = [("clients", "0006_pets")]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
