"""Печатная форма «Выписка из медкарты» — начальная, клиника может её менять."""

from django.conf import settings
from django.db import migrations

BODY = """<div style="display:flex; justify-content:space-between; border-bottom:2px solid #24566a; padding-bottom:6px;">
  <div><strong style="font-size:14pt;">{{ clinic.name }}</strong><br>{{ clinic.address }} {{ clinic.phone }}</div>
  <div style="text-align:right;">Дата приёма: {{ visit.date|datetime }}</div>
</div>
<h2 style="text-align:center;">Выписка из медицинской карты</h2>
<table>
  <tr><th style="width:30%">Пациент</th><td>{{ pet.name }}, {{ pet.species }}, {{ pet.breed }}, {{ pet.sex }}{% if pet.birth_date %}, д. р. {{ pet.birth_date|date }}{% endif %}</td></tr>
  <tr><th>Владелец</th><td>{{ client.full_name }}</td></tr>
  <tr><th>Цель обращения</th><td>{{ visit.purpose }}</td></tr>
  {% if visit.weight %}<tr><th>Вес</th><td>{{ visit.weight|qty }} кг</td></tr>{% endif %}
  {% if visit.temperature %}<tr><th>Температура</th><td>{{ visit.temperature|qty }} °C</td></tr>{% endif %}
  {% if visit.diagnoses %}<tr><th>Диагноз</th><td>{{ visit.diagnoses }}</td></tr>{% endif %}
</table>
{% if visit.treatment %}<h3>Описание лечения</h3>{{ visit.treatment|safe }}{% endif %}
{% if visit.recommendations %}<h3>Рекомендации и назначения</h3>{{ visit.recommendations|safe }}{% endif %}
{% if vaccinations %}<h3>Вакцинация</h3>
<table><tr><th>Вакцина</th><th>Дата</th><th>Следующая</th><th>Серия</th></tr>
{% for v in vaccinations %}<tr><td>{{ v.vaccine }}</td><td>{{ v.date|date }}</td><td>{{ v.next_date|date }}</td><td>{{ v.batch }}</td></tr>{% endfor %}
</table>{% endif %}
{% if visit.next_visit_date %}<p><strong>Повторный приём:</strong> {{ visit.next_visit_date|date }}</p>{% endif %}
<p style="margin-top:28px;">Врач: {{ doctor.full_name }} ________________</p>
"""


def create(apps, schema_editor):
    PrintTemplate = apps.get_model("core", "PrintTemplate")
    PrintTemplate.objects.get_or_create(
        kind="medcard", name="Выписка из медкарты",
        defaults={"body": BODY, "node_id": settings.NODE_ID},
    )  # fmt: skip


class Migration(migrations.Migration):
    dependencies = [("medical", "0002_initial_directories"), ("core", "0009_initial_file_categories")]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
