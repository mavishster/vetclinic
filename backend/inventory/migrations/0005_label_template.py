"""Печатная форма «Этикетка 58×40 мм» — для термопринтера этикеток. Клиника может менять."""

from django.conf import settings
from django.db import migrations

BODY = """<style>
  @page { size: 58mm 40mm; margin: 2mm; }
  body { font-size: 8pt; margin: 0; }
  .label { height: 36mm; page-break-after: always; overflow: hidden; }
  .label:last-child { page-break-after: auto; }
  .name { font-weight: bold; font-size: 8.5pt; line-height: 1.15; max-height: 3.5em; overflow: hidden; }
  .row { display: flex; justify-content: space-between; margin-top: 1mm; }
  .price { font-size: 12pt; font-weight: bold; }
  .code svg { width: 100%; height: 14mm; }
</style>
{% for l in labels %}
<div class="label">
  <div class="name">{{ l.name }}</div>
  <div class="row"><span>{{ l.unit }}{% if l.series %} · серия {{ l.series }}{% endif %}</span>
    {% if l.expiry_date %}<span>до {{ l.expiry_date|date }}</span>{% endif %}</div>
  <div class="row"><span class="price">{% if l.price %}{{ l.price|money }}{% endif %}</span><span>{{ l.article }}</span></div>
  <div class="code">{{ l.barcode_svg|safe }}</div>
</div>
{% endfor %}
"""


def create(apps, schema_editor):
    PrintTemplate = apps.get_model("core", "PrintTemplate")
    PrintTemplate.objects.get_or_create(
        kind="label", name="Этикетка 58×40 мм", defaults={"body": BODY, "node_id": settings.NODE_ID}
    )


class Migration(migrations.Migration):
    dependencies = [("inventory", "0004_inventory_return_minstock"), ("core", "0011_counterparty_details")]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
