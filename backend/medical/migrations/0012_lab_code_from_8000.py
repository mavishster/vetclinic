"""Номера для анализатора — с 8000 (решение клиники), а не с 50 000.

Номера, сдвинутые предыдущей миграцией в диапазон 50 000+, возвращаются в диапазон
с VISIT_LAB_CODE_START. Система ещё не в работе, номера никуда не введены.
"""

from django.conf import settings
from django.db import migrations

OLD_START = 50000


def shift(apps, schema_editor):
    Visit = apps.get_model("medical", "Visit")
    start = settings.VISIT_LAB_CODE_START
    if start >= OLD_START:
        return
    # С меньших номеров: новый диапазон ниже старого, столкновений по пути нет.
    for visit in Visit.objects.filter(lab_code__gte=OLD_START).order_by("lab_code"):
        Visit.objects.filter(pk=visit.pk).update(lab_code=visit.lab_code - OLD_START + start)


class Migration(migrations.Migration):
    dependencies = [("medical", "0011_lab_code_from_50000")]

    operations = [migrations.RunPython(shift, migrations.RunPython.noop)]
