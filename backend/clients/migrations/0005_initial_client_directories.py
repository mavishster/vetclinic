"""Начальные значения справочников клиентов. Дальше клиника меняет их сама."""

from django.conf import settings
from django.db import migrations

TYPES = ["Обычный", "Заводчик", "Приют / волонтёр", "Сотрудник клиники"]
SOURCES = [
    "Рекомендация знакомых",
    "Поиск в интернете",
    "Карты (2ГИС, Яндекс)",
    "Социальные сети",
    "Вывеска, проходили мимо",
    "Повторное обращение",
    "Другое",
]


def create(apps, schema_editor):
    for model, names in (("ClientType", TYPES), ("ClientSource", SOURCES)):
        Model = apps.get_model("clients", model)
        for name in names:
            Model.objects.get_or_create(name=name, defaults={"node_id": settings.NODE_ID})


class Migration(migrations.Migration):
    dependencies = [("clients", "0004_clients")]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
