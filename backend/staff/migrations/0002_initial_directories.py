"""Начальные должности, типы интервалов и шаблоны времени."""

from datetime import time

from django.conf import settings
from django.db import migrations

POSITIONS = ["Главный врач", "Врач", "Ассистент врача", "Администратор", "Лаборант", "Грумер"]
TYPES = [
    ("Приём", True, "#24566a"),
    ("Дежурство", True, "#5e7f66"),
    ("Отпуск", False, "#b5832a"),
    ("Больничный", False, "#b23a3a"),
    ("Выходной", False, "#8a8a8a"),
]
TEMPLATES = [
    ("Дневная 9–21", time(9), time(21), "Приём"),
    ("Утро 9–15", time(9), time(15), "Приём"),
    ("Вечер 15–21", time(15), time(21), "Приём"),
    ("Сутки 9–9", time(9), time(9), "Дежурство"),
    ("Ночная 21–9", time(21), time(9), "Дежурство"),
]


def create(apps, schema_editor):
    node = {"node_id": settings.NODE_ID}
    Position = apps.get_model("staff", "Position")
    IntervalType = apps.get_model("staff", "IntervalType")
    IntervalTemplate = apps.get_model("staff", "IntervalTemplate")
    for name in POSITIONS:
        Position.objects.get_or_create(name=name, defaults=node)
    types = {}
    for name, working, color in TYPES:
        types[name] = IntervalType.objects.get_or_create(
            name=name, defaults={**node, "is_working": working, "color": color}
        )[0]
    for name, start, end, type_name in TEMPLATES:
        IntervalTemplate.objects.get_or_create(
            name=name,
            defaults={**node, "start_time": start, "end_time": end, "interval_type": types[type_name]},
        )


class Migration(migrations.Migration):
    dependencies = [("staff", "0001_staff")]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
