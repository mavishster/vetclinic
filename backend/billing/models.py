"""Счета: модели данных.

Таблицы модуля — его личное дело: другие модули в них не пишут (PROJECT_PLAN, 4.3).
Цена фиксируется в строке при добавлении (ADR-008); себестоимость — при выполнении,
из партий склада (или вручную указанной у товара без складского учёта).
"""

from decimal import Decimal

from django.conf import settings
from django.db import models

from core.fields import MoneyField, QuantityField
from core.models import Document


class Invoice(Document):
    """Счёт клиента."""

    doc_type = "invoice"

    client = models.ForeignKey(
        "clients.Client", verbose_name="клиент", on_delete=models.PROTECT, related_name="+"
    )
    pet = models.ForeignKey(
        "clients.Pet",
        verbose_name="питомец",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="врач",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    appointment = models.ForeignKey(
        "scheduling.Appointment",
        verbose_name="приём",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    visit = models.ForeignKey(
        "medical.Visit",
        verbose_name="запись медкарты",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    warehouse = models.ForeignKey(
        "inventory.Warehouse",
        verbose_name="склад",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    # Скидка на весь счёт: процент или сумма. Пусто — действует скидка из карточки клиента.
    discount_percent = models.DecimalField(
        "скидка, %", max_digits=5, decimal_places=2, null=True, blank=True
    )
    discount_amount = MoneyField("скидка, ₽", null=True, blank=True)
    subtotal = MoneyField("сумма без скидки", default=Decimal("0"))
    discount_total = MoneyField("скидка итого", default=Decimal("0"))
    total = MoneyField("к оплате", default=Decimal("0"))
    is_quick = models.BooleanField("быстрый счёт", default=False)
    # Сколько оплачено (сумма распределений оплат) — для статуса «оплачен / частично / долг».
    paid_amount = MoneyField("оплачено", default=Decimal("0"))

    # Без отката можно поправить: врача, питомца и оплаченную сумму (её меняет касса).
    mutable_after_execution = ("doctor", "pet", "paid_amount")

    class Meta(Document.Meta):
        permissions = [
            ("rollback_invoice", "Откатывать выполненные и оплаченные счета"),
        ]
        verbose_name = "счёт"
        verbose_name_plural = "счета"

    @property
    def unpaid(self) -> Decimal:
        rest: Decimal = self.total - self.paid_amount
        return max(rest, Decimal("0"))

    @property
    def payment_status(self) -> str:
        if not self.is_executed:
            return "draft"
        if self.paid_amount <= 0:
            return "debt" if self.total > 0 else "paid"
        return "paid" if self.paid_amount >= self.total else "partial"

    def on_execute(self) -> None:
        from billing import services

        services.execute_invoice(self)

    def on_rollback(self) -> None:
        from billing import services

        services.rollback_invoice(self)


class InvoiceLine(models.Model):
    """Строка счёта. У комбинации «одной строкой» — строка-заголовок и строки состава."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(
        "catalog.Item", verbose_name="позиция", on_delete=models.PROTECT, related_name="+"
    )
    item_unit = models.ForeignKey(
        "catalog.ItemUnit",
        verbose_name="единица",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="children"
    )
    quantity = QuantityField("количество", default=Decimal("1"))
    qty_base = QuantityField("в единицах учёта", default=Decimal("0"))
    list_price = MoneyField("цена по прайсу", null=True, blank=True)
    price = MoneyField("цена")
    manual_price = models.BooleanField("цена изменена вручную", default=False)
    discount = MoneyField("скидка", default=Decimal("0"))
    amount = MoneyField("сумма", default=Decimal("0"))
    performer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="исполнитель",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    cost = MoneyField("себестоимость", default=Decimal("0"))
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        default_permissions = ()  # часть счёта
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return f"{self.item} × {self.quantity}"


class InvoiceLineBatch(models.Model):
    """Из каких партий списан товар строки и по какой себестоимости (ADR-007, ADR-008)."""

    line = models.ForeignKey(InvoiceLine, on_delete=models.CASCADE, related_name="batches")
    batch = models.ForeignKey("inventory.Batch", on_delete=models.PROTECT, related_name="+")
    qty_base = QuantityField("количество, в единицах учёта")
    cost_per_base = MoneyField("себестоимость единицы")

    class Meta:
        default_permissions = ()

    def __str__(self) -> str:
        return f"{self.line}: {self.batch} × {self.qty_base}"


class InvoicePayment(models.Model):
    """Распределение оплаты на счёт: какая сумма какой оплатой (или зачётом аванса) покрыта.

    payment_id — документ оплаты кассы (без внешнего ключа: касса — соседний модуль);
    пусто — зачёт аванса клиента. Деньги считает журнал баланса клиента, а эта таблица
    отвечает на вопрос «какие счета оплачены».
    """

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="payments")
    amount = MoneyField("сумма")
    payment_id = models.UUIDField("оплата", null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()  # часть счёта
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"{self.invoice}: {self.amount}"
