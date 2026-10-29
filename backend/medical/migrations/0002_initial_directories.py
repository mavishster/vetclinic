"""Начальные результаты посещения и частые диагнозы. Дальше клиника меняет списки сама."""

from django.conf import settings
from django.db import migrations

RESULTS = ["Выздоровление", "Улучшение", "Без изменений", "Ухудшение", "Назначен повторный приём",
           "Направлен в стационар", "Направлен к специалисту", "Эвтаназия", "Летальный исход"]  # fmt: skip
DIAGNOSES = ["Клинически здоров", "Гастроэнтерит", "Отит наружный", "Дерматит аллергический",
             "Мочекаменная болезнь", "Цистит", "Конъюнктивит", "Пародонтоз", "Травма", "Гельминтоз"]  # fmt: skip


def create(apps, schema_editor):
    node = {"node_id": settings.NODE_ID}
    for model, names in (("VisitResult", RESULTS), ("Diagnosis", DIAGNOSES)):
        Model = apps.get_model("medical", model)
        for name in names:
            Model.objects.get_or_create(name=name, defaults=node)


class Migration(migrations.Migration):
    dependencies = [("medical", "0001_visits")]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
