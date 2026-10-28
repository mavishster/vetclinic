"""Пример печатной формы — образец для клиники: шапка, таблица, фильтры."""

from django.conf import settings
from django.db import migrations

SAMPLE = """<div style="display:flex; justify-content:space-between; border-bottom:2px solid #24566a; padding-bottom:6px;">
  <div><strong style="font-size:14pt;">{{ clinic.name }}</strong><br>{{ clinic.address }}</div>
  <div style="text-align:right;">{{ clinic.phone }}<br>{{ today|date }}</div>
</div>

<h2>Пример печатной формы</h2>
<p>Это образец. Измените его или создайте свою форму. Переменные пишутся в двойных
фигурных скобках, например <code>{{ '{{ clinic.name }}' }}</code>.</p>

<table>
  <tr><th>Что показано</th><th>Как выглядит</th></tr>
  <tr><td>Деньги</td><td>{{ 1234.5|money }}</td></tr>
  <tr><td>Количество</td><td>{{ 1.500|qty }} мл</td></tr>
  <tr><td>Дата и время</td><td>{{ now|datetime }}</td></tr>
</table>

<p style="margin-top:24px;">Распечатал: {{ user.short_name }}</p>
"""


def create_sample(apps, schema_editor):
    PrintTemplate = apps.get_model("core", "PrintTemplate")
    PrintTemplate.objects.get_or_create(
        kind="general",
        name="Пример печатной формы",
        defaults={"body": SAMPLE, "node_id": settings.NODE_ID},
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0005_print_templates")]

    operations = [migrations.RunPython(create_sample, migrations.RunPython.noop)]
