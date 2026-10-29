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
    show_in_vaccinations = models.BooleanField("показывать в вакцинациях", default=False)

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
    """Товар или услуга."""

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
    is_call = models.BooleanField("вызов на дом", default=False)
    is_active = models.BooleanField("активен", default=True, db_index=True)
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
