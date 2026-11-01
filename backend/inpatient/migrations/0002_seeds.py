"""Палата по умолчанию и печатная форма «Лист назначений». Клиника меняет их сама."""

from django.conf import settings
from django.db import migrations

SHEET = """<h2 style="margin:0;">Лист назначений — {{ day|date }} (день {{ day_number }})</h2>
<p><b>{{ pet.name }}</b>, {{ pet.species }}, {{ pet.breed }} · владелец: {{ client.full_name }}<br>
Палата: {{ ward }}{% if place %}, место {{ place }}{% endif %} · врач: {{ doctor.full_name }}{% if reason %}<br>Диагноз: {{ reason }}{% endif %}</p>
<table><tr><th>Время</th><th>Препарат / процедура</th><th>Доза</th><th>Способ</th><th>Отметка</th><th>Кто</th><th>Примечание</th></tr>
{% for t in tasks %}<tr><td>{{ t.time }}</td><td>{{ t.title }}</td><td>{{ t.dose }}</td><td>{{ t.route }}</td><td>{{ t.status }}</td><td>{{ t.done_by }}</td><td>{{ t.note }}</td></tr>{% endfor %}
</table>
<p style="margin-top:20px;">Врач: ____________ Дежурный: ____________</p>
"""


def create(apps, schema_editor):
    Ward = apps.get_model("inpatient", "Ward")
    PrintTemplate = apps.get_model("core", "PrintTemplate")
    if not Ward.objects.exists():
        Ward.objects.create(name="Палата 1", kind="general", places=4, node_id=settings.NODE_ID)
    PrintTemplate.objects.get_or_create(
        kind="treatment_sheet", name="Лист назначений", defaults={"body": SHEET, "node_id": settings.NODE_ID}
    )


class Migration(migrations.Migration):
    dependencies = [("inpatient", "0001_inpatient"), ("core", "0012_user_ui_settings")]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
