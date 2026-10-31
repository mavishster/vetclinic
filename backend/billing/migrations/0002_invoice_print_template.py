"""Печатная форма «Счёт» — начальная, клиника может её менять."""

from django.conf import settings
from django.db import migrations

BODY = """<div style="display:flex; justify-content:space-between; border-bottom:2px solid #24566a; padding-bottom:6px;">
  <div><strong style="font-size:14pt;">{{ clinic.name }}</strong><br>{{ clinic.address }} {{ clinic.phone }}</div>
  <div style="text-align:right;">Счёт № {{ invoice.number }}<br>от {{ invoice.date|datetime }}</div>
</div>
<p>Клиент: <strong>{{ client.full_name }}</strong>{% if pet.name %} · питомец: {{ pet.name }}{% endif %}{% if doctor.short_name %} · врач: {{ doctor.short_name }}{% endif %}</p>
<table>
  <tr><th>№</th><th>Наименование</th><th>Кол-во</th><th>Цена</th><th>Скидка</th><th>Сумма</th></tr>
  {% for l in lines %}
  <tr><td>{{ loop.index }}</td><td>{{ l.name }}
    {% for c in l.composition %}<div style="font-size:8pt; color:#555;">— {{ c.name }} × {{ c.quantity|qty }}{% if c.amount is defined %} = {{ c.amount|money }}{% endif %}</div>{% endfor %}
  </td><td>{{ l.quantity|qty }} {{ l.unit }}</td><td>{{ l.price|money }}</td><td>{{ l.discount|money }}</td><td>{{ l.amount|money }}</td></tr>
  {% endfor %}
</table>
<p style="text-align:right;">Сумма: {{ invoice.subtotal|money }}{% if invoice.discount %} · скидка: {{ invoice.discount|money }}{% endif %}<br>
<strong style="font-size:13pt;">К оплате: {{ invoice.total|money }}</strong></p>
"""


def create(apps, schema_editor):
    PrintTemplate = apps.get_model("core", "PrintTemplate")
    PrintTemplate.objects.get_or_create(
        kind="invoice", name="Счёт", defaults={"body": BODY, "node_id": settings.NODE_ID}
    )


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_invoices"), ("core", "0011_counterparty_details")]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
