"""Касса: модели данных.

Таблицы модуля — его личное дело: другие модули в них не пишут (PROJECT_PLAN, 4.3).

Остаток кассы не хранится — он считается из журнала движений денег (ADR-004).
Касса работает сменами: смена открывается сама при первой операции и закрывается
кнопкой «Закрыть кассу» с итогами. Возврат оплаты — только пока её смена открыта.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models

from core.fields import MoneyField
from core.models import BaseModel, Directory, Document, LedgerEntry


class CashRegister(Directory):
    """Касса: наличные или безналичный приём (терминал, перевод)."""

    class Kind(models.TextChoices):
        CASH = "cash", "наличные"
        CASHLESS = "cashless", "безнал (терминал, перевод)"

    kind = models.CharField("вид", max_length=10, choices=Kind.choices, default=Kind.CASH)
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="ответственный",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta(Directory.Meta):
        verbose_name = "касса"
        verbose_name_plural = "кассы"


class CashShift(BaseModel):
    """Смена кассы: от первой операции до закрытия. Итоги — при закрытии."""

    register = models.ForeignKey(CashRegister, on_delete=models.PROTECT, related_name="shifts")
    opened_at = models.DateTimeField("открыта")
    closed_at = models.DateTimeField("закрыта", null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    income = MoneyField("поступило", default=Decimal("0"))
    expense = MoneyField("выдано", default=Decimal("0"))
    closing_balance = MoneyField("остаток на закрытии", default=Decimal("0"))

    class Meta:
        permissions = [
            ("close_shift", "Закрывать кассу (смену)"),
        ]
        verbose_name = "смена кассы"
        verbose_name_plural = "смены кассы"
        ordering = ["-opened_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["register"],
                condition=models.Q(closed_at__isnull=True, is_deleted=False),
                name="cash_one_open_shift",
            )
        ]

    def __str__(self) -> str:
        return f"{self.register}: смена с {self.opened_at:%d.%m %H:%M}"


class Payment(Document):
    """Оплата от клиента: наличные (со сдачей), безнал или смешанная; аванс — без счетов.

    Сдачу можно не выдавать, а оставить на балансе клиента — она станет авансом.
    Возврат оплаты = откат документа (только пока смена открыта).
    """

    doc_type = "payment"

    client = models.ForeignKey(
        "clients.Client", verbose_name="клиент", on_delete=models.PROTECT, related_name="+"
    )
    cash_register = models.ForeignKey(
        CashRegister,
        verbose_name="касса наличных",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    card_register = models.ForeignKey(
        CashRegister,
        verbose_name="касса безнала",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    cash_received = MoneyField("получено наличными", default=Decimal("0"))
    change_given = MoneyField("выдано сдачи", default=Decimal("0"))
    card_amount = MoneyField("безналом", default=Decimal("0"))
    # Какие счета оплатить (id счетов модуля «Счета»); пусто — внесение аванса.
    invoice_ids = models.JSONField("счета", default=list, blank=True)
    allocated = MoneyField("распределено на счета", default=Decimal("0"))

    class Meta(Document.Meta):
        permissions = [
            ("refund_payment", "Возвращать оплаты клиентам"),
        ]
        verbose_name = "оплата"
        verbose_name_plural = "оплаты"

    @property
    def amount(self) -> Decimal:
        """Сколько денег клиента осталось в клинике: наличные без сдачи + безнал."""
        total: Decimal = self.cash_received - self.change_given + self.card_amount
        return total

    def on_execute(self) -> None:
        from cash import services

        services.execute_payment(self)

    def on_rollback(self) -> None:
        from cash import services

        services.rollback_payment(self)


class CashOperation(Document):
    """Кассовая операция: внесение, выдача, перемещение между кассами, возврат аванса."""

    doc_type = "cash_operation"

    class Kind(models.TextChoices):
        INCOME = "income", "внесение денег"
        EXPENSE = "expense", "выдача денег"
        TRANSFER = "transfer", "перемещение между кассами"
        ADVANCE_RETURN = "advance_return", "возврат аванса клиенту"

    kind = models.CharField("вид", max_length=16, choices=Kind.choices)
    register = models.ForeignKey(
        CashRegister, verbose_name="касса", on_delete=models.PROTECT, related_name="+"
    )
    target_register = models.ForeignKey(
        CashRegister,
        verbose_name="в кассу",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    amount = MoneyField("сумма")
    counterparty = models.ForeignKey(
        "core.Counterparty",
        verbose_name="контрагент",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    client = models.ForeignKey(
        "clients.Client",
        verbose_name="клиент",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    purpose = models.CharField("назначение", max_length=255, blank=True)

    class Meta(Document.Meta):
        permissions = [
            ("return_advance", "Возвращать аванс клиенту"),
        ]
        verbose_name = "кассовая операция"
        verbose_name_plural = "кассовые операции"

    def on_execute(self) -> None:
        from cash import services

        services.execute_operation(self)

    def on_rollback(self) -> None:
        from cash import services

        services.rollback_cash_document(self)


class CashMovement(LedgerEntry):
    """Движение денег по кассе: + поступление, − выдача; в смене кассы."""

    amount_fields = ("amount",)

    register = models.ForeignKey(CashRegister, on_delete=models.PROTECT, related_name="+")
    shift = models.ForeignKey(CashShift, on_delete=models.PROTECT, related_name="movements")
    amount = MoneyField("сумма (± )")
    note = models.CharField("основание", max_length=255, blank=True)

    class Meta(LedgerEntry.Meta):
        verbose_name = "движение денег"
        verbose_name_plural = "движения денег"

    def __str__(self) -> str:
        return f"{self.register}: {self.amount:+}"
