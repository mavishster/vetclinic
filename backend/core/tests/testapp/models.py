"""Пример документа и журнала — только для тестов механик ядра."""

from django.db import models

from core import services
from core.fields import MoneyField
from core.models import Document, DocumentError, LedgerEntry


class SampleLedger(LedgerEntry):
    amount_fields = ("amount",)

    account = models.CharField(max_length=20)
    amount = MoneyField()


class SampleDocument(Document):
    doc_type = "sample"

    account = models.CharField(max_length=20, default="main")
    amount = MoneyField(default=0)
    forbid_rollback = models.BooleanField(default=False)

    def on_execute(self) -> None:
        if self.amount <= 0:
            raise DocumentError("Сумма должна быть больше нуля.")
        services.post_entry(SampleLedger, self, account=self.account, amount=self.amount)

    def on_rollback(self) -> None:
        if self.forbid_rollback:
            raise DocumentError("Откат запрещён: есть зависимые движения.")
        services.reverse_entries(SampleLedger, self)


class OtherDocument(Document):
    doc_type = "other"
