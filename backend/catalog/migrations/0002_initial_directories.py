"""Начальные единицы измерения и группы. Дальше клиника меняет списки сама."""

from decimal import Decimal

from django.conf import settings
from django.db import migrations

UNITS = ["шт.", "упак.", "таб.", "капс.", "мл", "л", "г", "кг", "доза", "амп.", "фл.", "усл."]
SERVICE_GROUPS = [
    "Приём и консультации",
    "Вакцинация",
    "Диагностика",
    "Лабораторные исследования",
    "Хирургия",
    "Процедуры и манипуляции",
    "Стационар",
]
GOODS_GROUPS = [
    ("Препараты", None, False),
    ("Вакцины", None, True),
    ("Расходные материалы", None, False),
    ("Корма", Decimal("25"), False),
    ("Зоотовары", Decimal("40"), False),
]


def create(apps, schema_editor):
    Unit = apps.get_model("catalog", "Unit")
    ItemGroup = apps.get_model("catalog", "ItemGroup")
    node = {"node_id": settings.NODE_ID}
    for name in UNITS:
        Unit.objects.get_or_create(name=name, defaults=node)
    for name in SERVICE_GROUPS:
        ItemGroup.objects.get_or_create(name=name, kind="service", defaults=node)
    for name, markup, vaccines in GOODS_GROUPS:
        ItemGroup.objects.get_or_create(
            name=name,
            kind="goods",
            defaults={**node, "markup_percent": markup, "show_in_vaccinations": vaccines},
        )


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_catalog")]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
