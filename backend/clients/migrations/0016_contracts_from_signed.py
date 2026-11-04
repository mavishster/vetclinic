"""Договоры, подписанные на планшете без заранее заведённого договора, появляются в «Договорах».

Раньше подписанный PDF ложился только в «Файлы», и карточка показывала «договора нет».
"""

from django.conf import settings
from django.db import migrations


def create(apps, schema_editor):
    SignatureRequest = apps.get_model("clients", "SignatureRequest")
    ClientContract = apps.get_model("clients", "ClientContract")
    Counter = apps.get_model("core", "DocumentCounter")
    for request in SignatureRequest.objects.filter(purpose="contract", status="signed", contract=None).exclude(result=None):
        counter, _ = Counter.objects.get_or_create(doc_type="contract", node_id=settings.NODE_ID, defaults={"last_number": 0})
        counter.last_number += 1
        counter.save(update_fields=["last_number"])
        contract = ClientContract.objects.create(
            client_id=request.client_id, number=f"{settings.NODE_ID}-{counter.last_number:06d}",
            date=request.signed_at.date(), attachment_id=request.result_id, node_id=settings.NODE_ID,
        )
        request.contract = contract
        request.save(update_fields=["contract"])


class Migration(migrations.Migration):
    dependencies = [("clients", "0015_alter_petownership_options_alter_petweight_options"), ("core", "0014_alter_documentcounter_options")]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
