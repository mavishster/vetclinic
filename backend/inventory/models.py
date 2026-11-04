"""Склад: модели данных.

Таблицы модуля — его личное дело: другие модули в них не пишут (PROJECT_PLAN, 4.3).

Остаток не хранится — он считается из журнала движений (ADR-004) в базовых единицах
товара (ADR-006). Каждый приход создаёт партии (ADR-007): серия, срок, закупочная цена.
"""

from django.conf import settings
from django.db import models

from core.fields import MoneyField, QuantityField
from core.models import BaseModel, Directory, Document, LedgerEntry


class Warehouse(Directory):
    """Склад. По счетам товар списывается только со складов реализации (оперативный),
    склад хранения (основной) пополняет их перемещениями.

    access_roles — какие роли видят склад (остатки, документы, отчёты). Пусто — все,
    у кого есть право на склад.
    """

    class Kind(models.TextChoices):
        SALE = "sale", "реализация"
        STORAGE = "storage", "хранение"

    kind = models.CharField("тип", max_length=8, choices=Kind.choices, default=Kind.SALE)
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="ответственный",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    access_roles = models.ManyToManyField(
        "auth.Group",
        verbose_name="видят роли",
        blank=True,
        related_name="+",
        help_text="Пусто — склад видят все, у кого есть право на склад",
    )

    class Meta(Directory.Meta):
        verbose_name = "склад"
        verbose_name_plural = "склады"


class Manufacturer(Directory):
    class Meta(Directory.Meta):
        verbose_name = "производитель"
        verbose_name_plural = "производители"


class StockDocument(Document):
    """Складской документ: приход, расход (списание), перемещение, инвентаризация,
    возврат поставщику.

    Один вид модели на все складские документы (DRY): у них общий жизненный цикл —
    черновик → выполнен → откат (ADR-005), различается только то, что делает выполнение.
    """

    class Kind(models.TextChoices):
        RECEIPT = "receipt", "приход"
        WRITE_OFF = "write_off", "расход"
        TRANSFER = "transfer", "перемещение"
        INVENTORY = "inventory", "инвентаризация"
        RETURN = "return", "возврат поставщику"

    kind = models.CharField("вид", max_length=10, choices=Kind.choices)
    warehouse = models.ForeignKey(
        Warehouse, verbose_name="склад", on_delete=models.PROTECT, related_name="+"
    )
    target_warehouse = models.ForeignKey(
        Warehouse,
        verbose_name="на склад",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    counterparty = models.ForeignKey(
        "core.Counterparty",
        verbose_name="поставщик",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    supplier_number = models.CharField("№ накладной поставщика", max_length=50, blank=True)
    supplier_date = models.DateField("дата накладной поставщика", null=True, blank=True)
    reason = models.CharField("причина списания", max_length=200, blank=True)

    class Meta(Document.Meta):
        permissions = [
            ("rollback_stockdocument", "Откатывать выполненные складские документы"),
        ]
        verbose_name = "складской документ"
        verbose_name_plural = "складские документы"
        # Нумерация своя у каждого вида: приход № K1-000001 и расход № K1-000001 — разные.
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "number"], name="inventory_stockdocument_unique_number"
            )
        ]

    @property
    def doc_type(self) -> str:  # type: ignore[override]
        # У каждого вида документа своя нумерация.
        return f"stock_{self.kind}"

    def on_execute(self) -> None:
        from inventory import services

        services.execute_stock_document(self)

    def on_rollback(self) -> None:
        from inventory import services

        services.rollback_stock_document(self)


class StockLine(models.Model):
    """Строка складского документа. Количество вводится в любой единице товара."""

    document = models.ForeignKey(StockDocument, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(
        "catalog.Item", verbose_name="товар", on_delete=models.PROTECT, related_name="+"
    )
    item_unit = models.ForeignKey(
        "catalog.ItemUnit", verbose_name="единица", on_delete=models.PROTECT, related_name="+"
    )
    quantity = QuantityField("количество")
    qty_base = QuantityField("в единицах учёта", editable=False, default=0)
    # Инвентаризация: сколько было по учёту на момент заполнения (в единицах учёта);
    # quantity / qty_base — сколько насчитали.
    qty_expected = QuantityField("по учёту", null=True, blank=True)
    # Приход: закупочная цена за единицу строки, НДС, серия, срок, производитель.
    price = MoneyField("цена за единицу", null=True, blank=True)
    vat_percent = models.DecimalField(
        "НДС, %", max_digits=5, decimal_places=2, null=True, blank=True
    )
    series = models.CharField("серия", max_length=50, blank=True)
    expiry_date = models.DateField("срок годности", null=True, blank=True)
    manufacturer = models.ForeignKey(
        Manufacturer, verbose_name="производитель", on_delete=models.PROTECT, null=True, blank=True
    )
    # Расход и перемещение: партия (пусто — списать по сроку годности, старые первыми).
    # Приход: партия, созданная при выполнении.
    batch = models.ForeignKey(
        "Batch",
        verbose_name="партия",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "строка складского документа"
        verbose_name_plural = "строки складских документов"
        default_permissions = ()  # часть документа
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return f"{self.item} × {self.quantity}"


class Batch(BaseModel):
    """Партия товара: из какого прихода, серия, срок годности, закупочная цена."""

    item = models.ForeignKey(
        "catalog.Item", verbose_name="товар", on_delete=models.PROTECT, related_name="+"
    )
    receipt_line = models.OneToOneField(
        StockLine, on_delete=models.PROTECT, null=True, blank=True, related_name="created_batch"
    )
    series = models.CharField("серия", max_length=50, blank=True)
    expiry_date = models.DateField("срок годности", null=True, blank=True, db_index=True)
    manufacturer = models.ForeignKey(
        Manufacturer, verbose_name="производитель", on_delete=models.PROTECT, null=True, blank=True
    )
    cost_per_base = MoneyField("закупочная цена за единицу учёта")
    vat_percent = models.DecimalField(
        "НДС, %", max_digits=5, decimal_places=2, null=True, blank=True
    )
    received_at = models.DateTimeField("поступила")

    class Meta:
        verbose_name = "партия"
        verbose_name_plural = "партии"
        ordering = ["expiry_date", "received_at"]

    def __str__(self) -> str:
        expiry = f" до {self.expiry_date:%m.%Y}" if self.expiry_date else ""
        return f"{self.series or 'без серии'}{expiry}"


class StockMovement(LedgerEntry):
    """Движение товара: + приход, − расход, в базовых единицах, со своей себестоимостью."""

    amount_fields = ("qty_base",)

    item = models.ForeignKey("catalog.Item", on_delete=models.PROTECT, related_name="+")
    batch = models.ForeignKey(
        Batch, on_delete=models.PROTECT, null=True, blank=True, related_name="movements"
    )
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="+")
    qty_base = QuantityField("количество (± в единицах учёта)")
    cost_per_base = MoneyField("себестоимость единицы учёта", default=0)

    class Meta(LedgerEntry.Meta):
        verbose_name = "движение товара"
        verbose_name_plural = "остатки и движения товаров"
        indexes = [
            *LedgerEntry.Meta.indexes,
            models.Index(fields=["item", "warehouse", "batch"]),
        ]

    def __str__(self) -> str:
        return f"{self.item}: {self.qty_base:+}"


class MinStock(BaseModel):
    """Минимальный остаток товара: ниже — пора заказывать. Склад пуст — по всем складам."""

    item = models.ForeignKey(
        "catalog.Item", verbose_name="товар", on_delete=models.PROTECT, related_name="+"
    )
    warehouse = models.ForeignKey(
        Warehouse,
        verbose_name="склад",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    min_qty = QuantityField("минимум, в единицах учёта")

    class Meta:
        verbose_name = "минимальный остаток"
        verbose_name_plural = "минимальные остатки"
        constraints = [
            models.UniqueConstraint(
                fields=["item", "warehouse"],
                condition=models.Q(is_deleted=False),
                name="inventory_minstock_unique",
            )
        ]

    def __str__(self) -> str:
        return f"{self.item}: {self.min_qty}"
