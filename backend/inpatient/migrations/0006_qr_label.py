"""QR-этикетка пациента: право печати и печатная форма (А4, этикетки для вырезания)."""

from django.conf import settings
from django.db import migrations

LABEL = """<style>
@page { size: A4; margin: 5mm; }
body { margin: 0; }
.sheet { font-size: 0; page-break-after: always; }
.sheet:last-child { page-break-after: auto; }
.label { display: inline-block; vertical-align: top; box-sizing: border-box; overflow: hidden;
  width: {{ size.label_w }}mm; height: {{ size.label_h }}mm; padding: 5mm; text-align: center;
  border: 0.3mm dashed #888; font-size: 12pt; }
.name { font-size: 26pt; font-weight: bold; line-height: 1.1; margin-bottom: 2mm; }
.row { line-height: 1.3; margin-bottom: 1mm; }
.row small { color: #666; }
.qr { margin: 4mm auto 0; width: {{ size.qr }}mm; height: {{ size.qr }}mm; }
.qr img { width: 100%; height: 100%; }
.hint { margin-top: 2mm; font-size: 8pt; color: #666; }
</style>
{% for sheet in sheets %}<div class="sheet">{% for label in sheet %}<div class="label">
{% for f in label.fields %}{% if f.code == 'pet_name' %}<div class="name">{{ f.value }}</div>{% else %}<div class="row"><small>{{ f.label }}:</small> {{ f.value }}</div>{% endif %}{% endfor %}
<div class="qr"><img src="{{ label.qr }}"></div>
<div class="hint">Сканируйте камерой телефона</div>
</div>{% endfor %}</div>{% endfor %}
"""


def create(apps, schema_editor):
    PrintTemplate = apps.get_model("core", "PrintTemplate")
    PrintTemplate.objects.get_or_create(
        kind="hospitalization_qr",
        name="QR-этикетка пациента",
        defaults={"body": LABEL, "node_id": settings.NODE_ID},
    )


class Migration(migrations.Migration):
    dependencies = [("inpatient", "0005_alter_hospitalization_options"), ("core", "0017_clinic_qr_base_url_clinic_qr_fields_and_more")]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
