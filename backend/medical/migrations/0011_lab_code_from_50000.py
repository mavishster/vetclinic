"""Номера для анализатора — с VISIT_LAB_CODE_START (по умолчанию 50 000).

Уже выданные номера (1, 2, 3…) сдвигаются в новый диапазон: система ещё не в работе,
номера никуда не введены. Счётчик не меняется — к нему прибавляется стартовое число.
"""

from django.conf import settings
from django.db import migrations


def shift(apps, schema_editor):
    Visit = apps.get_model("medical", "Visit")
    offset = settings.VISIT_LAB_CODE_START - 1
    # С больших номеров — чтобы не столкнуться с уникальностью по пути.
    for visit in Visit.objects.exclude(lab_code=None).order_by("-lab_code"):
        if visit.lab_code < settings.VISIT_LAB_CODE_START:
            Visit.objects.filter(pk=visit.pk).update(lab_code=visit.lab_code + offset)


class Migration(migrations.Migration):
    dependencies = [("medical", "0010_visit_lab_code")]

    operations = [migrations.RunPython(shift, migrations.RunPython.noop)]
