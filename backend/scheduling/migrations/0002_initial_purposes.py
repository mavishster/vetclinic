"""Начальные цели обращения — как в VetManager. Дальше клиника меняет список сама."""

from django.conf import settings
from django.db import migrations

PURPOSES = [
    # название, вид, минут, цвет, показывать в ЛК
    ("Первичный", "general", 30, "#24566a", True),
    ("Повторный", "general", 20, "#3a6f8f", True),
    ("Вакцинация", "vaccination", 20, "#3c7a4e", True),
    ("Взятие анализа", "analysis", 15, "#6b4c9a", True),
    ("Экстренный", "general", 30, "#b23a3a", True),
    ("Хирургия", "general", 60, "#8a3b12", True),
    ("Рентген", "general", 20, "#5e7f66", True),
    ("УЗИ", "general", 30, "#5e7f66", True),
    ("Груминг", "general", 60, "#b5832a", True),
    ("Стационар", "general", 30, "#4f5b62", False),
    ("Эвтаназия", "general", 30, "#4f5b62", False),
    ("Звонок", "call", 10, "#8a8a8a", False),
    ("Задача", "task", 10, "#8a8a8a", False),
]


def create(apps, schema_editor):
    VisitPurpose = apps.get_model("scheduling", "VisitPurpose")
    for name, kind, minutes, color, portal in PURPOSES:
        VisitPurpose.objects.get_or_create(
            name=name,
            defaults={
                "node_id": settings.NODE_ID, "kind": kind, "duration_minutes": minutes,
                "color": color, "show_in_portal": portal,
            },
        )  # fmt: skip


class Migration(migrations.Migration):
    dependencies = [("scheduling", "0001_appointments")]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
