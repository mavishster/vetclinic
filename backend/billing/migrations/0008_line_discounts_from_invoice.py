"""Скидка теперь в каждой строке. Черновикам переносится прежняя скидка счёта
(или скидка из карточки клиента) в строки без ручной цены. Выполненные счета не трогаются:
их суммы уже записаны."""

from django.db import migrations


def move(apps, schema_editor):
    Invoice = apps.get_model("billing", "Invoice")
    InvoiceLine = apps.get_model("billing", "InvoiceLine")
    for invoice in Invoice.objects.filter(status="draft").select_related("client"):
        percent = invoice.discount_percent
        if percent is None and invoice.discount_amount is None:
            percent = invoice.client.discount_percent or None
        if not percent:
            continue
        parents = set(InvoiceLine.objects.filter(invoice=invoice).exclude(parent=None).values_list("parent_id", flat=True))
        InvoiceLine.objects.filter(invoice=invoice, manual_price=False).exclude(pk__in=parents).update(
            discount_percent=percent
        )


class Migration(migrations.Migration):
    dependencies = [("billing", "0007_line_discount_percent")]

    operations = [migrations.RunPython(move, migrations.RunPython.noop)]
