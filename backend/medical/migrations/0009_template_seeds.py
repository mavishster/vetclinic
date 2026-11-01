"""Начальные текстовые шаблоны и печатная форма «Памятка владельцу». Клиника меняет их сама."""

from django.conf import settings
from django.db import migrations

TEXTS = [
    ("Первичный осмотр", "treatment", None, (
        "<p><b>Жалобы:</b> [___ со слов владельца]</p>"
        "<p><b>Анамнез:</b> болеет [___ сколько дней]. Аппетит [___ сохранён / снижен], "
        "питьё [___], рвота [___ нет / есть], стул [___].</p>"
        "<p><b>Объективно:</b> {вид}, {порода}, {возраст}, вес {вес} кг, t {температура} °C. "
        "Общее состояние [___ удовлетворительное]. Слизистые [___ розовые, влажные]. "
        "Лимфоузлы [___ не увеличены]. Живот [___ мягкий, безболезненный].</p>"
        "<p><b>Предварительный диагноз:</b> [___]</p>"
    )),
    ("Вакцинация — осмотр", "treatment", "vaccination", (
        "<p>Клинический осмотр перед вакцинацией: {кличка}, {возраст}, вес {вес} кг, "
        "t {температура} °C. Общее состояние удовлетворительное, противопоказаний к вакцинации "
        "не выявлено. Вакцинирован(а): [___ препарат, серия].</p>"
    )),
    ("Вакцинация — рекомендации", "recommendations", "vaccination", (
        "<p>В течение 2–3 недель после вакцинации ограничить контакты с другими животными, "
        "не купать, избегать переохлаждения. Возможны вялость и снижение аппетита в течение суток. "
        "При отёке морды, рвоте, затруднённом дыхании — сразу обратиться в клинику.</p>"
        "<p>Следующая вакцинация: [___ дата].</p>"
    )),
    ("Гастроэнтерит — рекомендации", "recommendations", None, (
        "<p>Голодная диета [___ 12 часов], вода — без ограничений, небольшими порциями. "
        "Затем лечебный корм [___ название] маленькими порциями 4–6 раз в день "
        "в течение [___ 7 дней].</p>"
        "<p>Повторный осмотр: [___ дата]. При ухудшении состояния, повторной рвоте, крови в стуле — "
        "обратиться в клинику немедленно.</p>"
    )),
]

PRINT_BODY = """<div style="display:flex; justify-content:space-between; border-bottom:2px solid #24566a; padding-bottom:6px;">
  <div><strong style="font-size:14pt;">{{ clinic.name }}</strong><br>{{ clinic.address }} {{ clinic.phone }}</div>
  <div style="text-align:right;">{{ visit.date|datetime }}</div>
</div>
<h2 style="text-align:center;">Памятка владельцу</h2>
<p><b>{{ pet.name }}</b>, {{ pet.species }}{% if pet_age %}, {{ pet_age }}{% endif %}{% if visit.weight %}, {{ visit.weight|qty }} кг{% endif %}.
Владелец: {{ client.full_name }}.</p>
{% if visit.diagnoses %}<p><b>Диагноз:</b> {{ visit.diagnoses }}</p>{% endif %}
{% if prescriptions %}<h3>Назначения</h3>
<table><tr><th>Препарат</th><th>Доза</th><th>Как давать</th><th>Сколько раз</th><th>Дней</th><th>Примечание</th></tr>
{% for p in prescriptions %}<tr><td>{{ p.drug }}</td><td>{{ p.dose }}</td><td>{{ p.route }}</td><td>{{ p.frequency }}</td><td>{{ p.days or "" }}</td><td>{{ p.comment }}</td></tr>{% endfor %}
</table>{% endif %}
{% if visit.recommendations %}<h3>Рекомендации</h3>{{ visit.recommendations|safe }}{% endif %}
{% if visit.next_visit_date %}<p><b>Повторный приём:</b> {{ visit.next_visit_date|date }}</p>{% endif %}
<p style="margin-top:24px;">Врач: {{ doctor.full_name }}</p>
"""


def create(apps, schema_editor):
    TextTemplate = apps.get_model("medical", "TextTemplate")
    VisitPurpose = apps.get_model("scheduling", "VisitPurpose")
    PrintTemplate = apps.get_model("core", "PrintTemplate")
    node = {"node_id": settings.NODE_ID}
    for name, section, kind, body in TEXTS:
        purpose = VisitPurpose.objects.filter(kind=kind).order_by("created_at").first() if kind else None
        TextTemplate.objects.get_or_create(
            name=name, owner=None, defaults={**node, "section": section, "purpose": purpose, "body_html": body}
        )
    PrintTemplate.objects.get_or_create(
        kind="prescriptions", name="Памятка владельцу", defaults={**node, "body": PRINT_BODY}
    )


class Migration(migrations.Migration):
    dependencies = [
        ("medical", "0008_templates_prescriptions"),
        ("scheduling", "0002_initial_purposes"),
        ("core", "0012_user_ui_settings"),
    ]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
