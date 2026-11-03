"""Начальные документы на подпись: договор и согласие на обработку ПДн и фото.

Это типовые тексты — клиника заменит их своими (формулировки стоит согласовать с юристом).
"""

from django.conf import settings
from django.db import migrations

CONTRACT = """<h2 style="text-align:center;">Договор на оказание ветеринарных услуг{% if contract.number %} № {{ contract.number }}{% endif %}</h2>
<p style="text-align:right;">{{ (contract.date or today)|date }}</p>
<p>{{ clinic.name }} (далее — Клиника) и {{ client.full_name }} (далее — Владелец){% if client.phones %}, телефон {{ client.phones }}{% endif %}{% if client.address %}, адрес: {{ client.address }}{% endif %}, заключили настоящий договор.</p>
<p>1. Клиника оказывает ветеринарные услуги животным Владельца{% if pets %}: {% for p in pets %}{{ p.name }} ({{ p.species }}){% if not loop.last %}, {% endif %}{% endfor %}{% endif %}, а Владелец оплачивает их по прейскуранту Клиники.</p>
<p>2. Перед медицинскими вмешательствами Клиника информирует Владельца о целях, методах и возможных рисках; Владелец даёт согласие или отказ.</p>
<p>3. Владелец соглашается, что подпись, поставленная им на планшете Клиники, равнозначна собственноручной подписи на бумаге.</p>
<p>4. Договор действует бессрочно и может быть расторгнут любой из сторон с уведомлением другой стороны.</p>
<p style="margin-top:20px;">Клиника: {{ clinic.name }}{% if clinic.address %}, {{ clinic.address }}{% endif %}{% if clinic.phone %}, {{ clinic.phone }}{% endif %}</p>
<p>Владелец: {{ client.full_name }}</p>
"""

CONSENT = """<h2 style="text-align:center;">Согласие на обработку персональных данных и фотографирование</h2>
<p>Я, {{ client.full_name }}{% if client.phones %}, телефон {{ client.phones }}{% endif %}, даю согласие {{ clinic.name }}{% if clinic.address %} ({{ clinic.address }}){% endif %} на обработку моих персональных данных: ФИО, телефонов, адреса, email, сведений о моих животных и оказанных услугах, а также на фотографирование и хранение моего фото для идентификации владельца животного — в целях оказания ветеринарных услуг, ведения медицинской документации, записи на приём и напоминаний.</p>
<p>Обработка включает сбор, запись, хранение, уточнение, использование и удаление данных, в том числе с помощью компьютерных программ. Согласие действует до его отзыва; отозвать его можно письменным заявлением в Клинику.</p>
<p>Подпись, поставленная мной на планшете Клиники, равнозначна собственноручной.</p>
<p style="text-align:right;">{{ today|date }}</p>
"""


def create(apps, schema_editor):
    PrintTemplate = apps.get_model("core", "PrintTemplate")
    for name, body in (("Договор на оказание ветеринарных услуг", CONTRACT),
                       ("Согласие на обработку ПДн и фотографирование", CONSENT)):  # fmt: skip
        PrintTemplate.objects.get_or_create(
            kind="client_document", name=name, defaults={"body": body, "node_id": settings.NODE_ID}
        )


class Migration(migrations.Migration):
    dependencies = [("clients", "0011_signing_photo"), ("core", "0012_user_ui_settings")]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
