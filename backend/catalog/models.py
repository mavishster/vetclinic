"""Каталог товаров и услуг: модели данных.

Таблицы модуля — его личное дело: другие модули в них не пишут (PROJECT_PLAN, 4.3).

Остатки на складе хранятся в базовой единице товара (ADR-006), а продаётся и
закупается товар в любых своих единицах: «упаковка = 216 таблеток».
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.functions import Lower

from core.fields import MoneyField, QuantityField
from core.models import BaseModel, Directory


class Kind(models.TextChoices):
    GOODS = "goods", "товар"
    SERVICE = "service", "услуга"
    COMBO = "combo", "комбинация"


class PreventionKind(models.TextChoices):
    """Вид профилактики, к которому относится товар или услуга (для медкарты и отчётов).

    Коды совпадают с видами профилактики медкарты: так препарат или услуга,
    отмеченные в записи, подсказывают врачу записать процедуру.
    """

    VACCINATION = "vaccination", "вакцинация"
    DEWORMING = "deworming", "дегельминтизация"
    ECTOPARASITES = "ectoparasites", "обработка от эктопаразитов"
    STERILIZATION = "sterilization", "стерилизация / кастрация"
    CHIPPING = "chipping", "чипирование"


class Unit(Directory):
    """Единица измерения: шт., таб., мл, упак., доза…"""

    class Meta(Directory.Meta):
        verbose_name = "единица измерения"
        verbose_name_plural = "единицы измерения"


class ItemGroup(Directory):
    """Группа товаров или услуг. Наценка группы действует для товаров без своей наценки."""

    unique_within = ("kind",)

    kind = models.CharField("для чего", max_length=10, choices=Kind.choices, default=Kind.GOODS)
    markup_percent = models.DecimalField(
        "наценка группы, %",
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    prevention_kind = models.CharField(
        "профилактика", max_length=16, choices=PreventionKind.choices, blank=True,
        help_text="Товары группы предлагаются в медкарте для этого вида профилактики",
    )  # fmt: skip

    class Meta(Directory.Meta):
        verbose_name = "группа товаров и услуг"
        verbose_name_plural = "группы товаров и услуг"
        constraints = [
            models.UniqueConstraint(
                "kind",
                Lower("name"),
                condition=models.Q(is_deleted=False),
                name="catalog_itemgroup_unique_name_in_kind",
            )
        ]


class Item(BaseModel):
    """Товар, услуга или комбинация (набор товаров и услуг, CombinationLine)."""

    class PrintMode(models.TextChoices):
        FULL = "full", "все позиции с ценами"
        NAME = "name", "только название комбинации"
        SERVICES = "services", "название и услуги с ценами"
        COMPOSITION = "composition", "название и состав без цен"

    kind = models.CharField("вид", max_length=10, choices=Kind.choices, default=Kind.GOODS)
    name = models.CharField("название", max_length=255)
    description = models.TextField("описание", blank=True)
    group = models.ForeignKey(ItemGroup, verbose_name="группа", on_delete=models.PROTECT)
    article = models.CharField("артикул", max_length=50, blank=True, db_index=True)
    base_unit = models.ForeignKey(
        Unit, verbose_name="единица учёта", on_delete=models.PROTECT, related_name="+"
    )
    barcode = models.CharField("штрихкод", max_length=50, blank=True, db_index=True)
    # Себестоимость базовой единицы вручную: для услуг и товаров без складского учёта.
    # У товаров со складом себестоимость берётся из партий (этап 3).
    manual_cost = MoneyField("себестоимость (вручную)", null=True, blank=True)
    for_sale = models.BooleanField("продаётся", default=True)
    combo_only = models.BooleanField(
        "только для комбинаций", default=False,
        help_text="Отдельно в счёт не добавляется — только в составе комбинаций",
    )  # fmt: skip
    # Склад отмечает товар при первом выполненном приходе (через catalog.services).
    stock_tracked = models.BooleanField("ведётся складской учёт", default=False, editable=False)
    is_call = models.BooleanField("вызов на дом", default=False)
    is_active = models.BooleanField("активен", default=True, db_index=True)
    # Вид профилактики у самой позиции (если отличается от группы): «Кастрация кота» →
    # стерилизация, «Чипирование» → чипирование.
    prevention_kind = models.CharField(
        "профилактика", max_length=16, choices=PreventionKind.choices, blank=True
    )
    # Для комбинаций: шаблонная просто добавляет позиции в счёт по отдельности,
    # обычная — одной строкой со своим составом (ADR-017).
    is_template = models.BooleanField("шаблонная комбинация", default=False)
    print_mode = models.CharField(
        "печать комбинации", max_length=12, choices=PrintMode.choices, default=PrintMode.FULL
    )
    responsible = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        verbose_name="ответственные сотрудники",
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "товар или услуга"
        verbose_name_plural = "товары и услуги"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ItemUnit(BaseModel):
    """Единица продажи и закупки товара со своей ценой.

    ratio — сколько базовых единиц в этой единице: упаковка таблеток = 216.
    Цена: фиксированная (price) или наценка от закупки (markup_percent;
    пусто — берётся наценка группы, 0 — действительно 0 %, ADR-016).
    История изменения цен ведётся журналом аудита.
    """

    class Pricing(models.TextChoices):
        FIXED = "fixed", "фиксированная цена"
        MARKUP = "markup", "наценка от закупки"

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="units")
    unit = models.ForeignKey(Unit, verbose_name="единица", on_delete=models.PROTECT)
    ratio = QuantityField(
        "базовых единиц в одной", default=Decimal("1"), validators=[MinValueValidator(0)]
    )
    for_sale = models.BooleanField("для продажи", default=True)
    for_purchase = models.BooleanField("для закупки", default=False)
    pricing = models.CharField(
        "цена", max_length=10, choices=Pricing.choices, default=Pricing.FIXED
    )
    price = MoneyField("цена", null=True, blank=True)
    markup_percent = models.DecimalField(
        "наценка, %", max_digits=7, decimal_places=2, null=True, blank=True
    )
    price_min = MoneyField("минимальная цена", null=True, blank=True)
    price_max = MoneyField("максимальная цена", null=True, blank=True)
    rounding = MoneyField("округлять до", default=Decimal("0.01"))
    barcode = models.CharField("штрихкод", max_length=50, blank=True, db_index=True)

    class Meta:
        default_permissions = ()  # часть карточки товара
        ordering = ["ratio"]
        constraints = [
            models.UniqueConstraint(
                fields=["item", "unit"],
                condition=models.Q(is_deleted=False),
                name="catalog_itemunit_unique_unit",
            )
        ]
        verbose_name = "единица товара"
        verbose_name_plural = "единицы товара"

    def __str__(self) -> str:
        return f"{self.item} ({self.unit})"


class CombinationLine(models.Model):
    """Позиция комбинации: товар или услуга в своей единице, количество, цена.

    price_override пусто — позиция идёт по текущей цене прайса; задано — цена
    зафиксирована для этой комбинации (ADR-017). «Сбросить цены» = очистить.
    """

    combination = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="lines")
    item_unit = models.ForeignKey(ItemUnit, verbose_name="позиция", on_delete=models.PROTECT)
    quantity = QuantityField("количество", default=Decimal("1"))
    price_override = MoneyField("своя цена", null=True, blank=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        default_permissions = ()  # часть карточки комбинации
        ordering = ["position", "id"]
        verbose_name = "позиция комбинации"
        verbose_name_plural = "позиции комбинации"

    def __str__(self) -> str:
        return f"{self.item_unit} × {self.quantity}"
