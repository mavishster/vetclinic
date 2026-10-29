"""Каталог товаров и услуг: публичный вход модуля.

Отвечает за: товары, услуги, единицы, группы, цены и наценки, комбинации.

Другие модули обращаются к модулю только через функции этого файла.
Бизнес-правила живут здесь, а не в моделях и не в API (ENGINEERING.md).
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, TypedDict

from django.db import transaction
from django.db.models import Q, QuerySet

from catalog.models import Item, ItemUnit, Kind


class CatalogError(Exception):
    """Ошибка в данных каталога. Текст — для пользователя."""


# --- Цены --------------------------------------------------------------------------


def round_price(value: Decimal, step: Decimal) -> Decimal:
    """Округлить цену до шага: до копеек (0.01), рубля (1), десяти рублей (10)…"""
    step = step if step and step > 0 else Decimal("0.01")
    rounded = (value / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step
    return rounded.quantize(Decimal("0.01"))


def effective_markup(item_unit: ItemUnit) -> Decimal:
    """Наценка единицы: своя, иначе группы, иначе 0 (ADR-016: пусто — наследовать)."""
    if item_unit.markup_percent is not None:
        return item_unit.markup_percent
    group_markup = item_unit.item.group.markup_percent
    return group_markup if group_markup is not None else Decimal("0")


def price_of(item_unit: ItemUnit, cost_per_base: Decimal | None = None) -> Decimal | None:
    """Цена продажи единицы.

    Фиксированная — как задана. С наценкой — закупочная цена базовой единицы × сколько
    базовых в этой единице × (1 + наценка), с округлением. Закупочную цену передаёт склад
    (цена партии); если не передана — берётся себестоимость товара, указанная вручную.
    Нет ни того, ни другого — цена неизвестна (None).
    """
    if item_unit.pricing == ItemUnit.Pricing.FIXED:
        fixed: Decimal | None = item_unit.price
        return fixed
    cost = cost_per_base if cost_per_base is not None else item_unit.item.manual_cost
    if cost is None:
        return None
    raw = cost * item_unit.ratio * (1 + effective_markup(item_unit) / 100)
    return round_price(raw, item_unit.rounding)


def is_price_allowed(item_unit: ItemUnit, price: Decimal) -> bool:
    """Можно ли продать по этой цене (плавающая цена: в пределах от min до max)."""
    if item_unit.price_min is not None and price < item_unit.price_min:
        return False
    return not (item_unit.price_max is not None and price > item_unit.price_max)


# --- Карточка товара ---------------------------------------------------------------


class UnitData(TypedDict, total=False):
    id: Any
    unit: Any  # Unit или его id
    ratio: Decimal
    for_sale: bool
    for_purchase: bool
    pricing: str
    price: Decimal | None
    markup_percent: Decimal | None
    price_min: Decimal | None
    price_max: Decimal | None
    rounding: Decimal
    barcode: str


def _check_unit(item: Item, unit: ItemUnit) -> None:
    label = f"Единица «{unit.unit}»"
    if unit.ratio <= 0:
        raise CatalogError(f"{label}: количество базовых единиц должно быть больше нуля.")
    if unit.pricing == ItemUnit.Pricing.FIXED:
        if unit.for_sale and unit.price is None:
            raise CatalogError(f"{label}: укажите цену.")
        if unit.price is not None and unit.price < 0:
            raise CatalogError(f"{label}: цена не может быть отрицательной.")
    elif unit.markup_percent is not None and unit.markup_percent < 0:
        raise CatalogError(f"{label}: наценка не может быть отрицательной.")
    low, high = unit.price_min, unit.price_max
    if low is not None and high is not None and low > high:
        raise CatalogError(f"{label}: минимальная цена больше максимальной.")
    fixed_price = unit.price if unit.pricing == ItemUnit.Pricing.FIXED else None
    if fixed_price is not None and not is_price_allowed(unit, fixed_price):
        raise CatalogError(f"{label}: цена вне диапазона от минимальной до максимальной.")


def _unit_id(data: UnitData) -> Any:
    """Единица в данных может быть объектом Unit или его id."""
    value = data.get("unit")
    return getattr(value, "pk", value)


@transaction.atomic
def save_item(item: Item, units: list[UnitData] | None = None) -> Item:
    """Сохранить товар или услугу вместе с единицами (если переданы).

    Единицы, которых нет в переданном списке, удаляются (мягко).
    Цены меняются у существующих записей — так в журнале остаётся история цен.
    """
    item.name = item.name.strip()
    if not item.name:
        raise CatalogError("Укажите название.")
    if item.group.kind != item.kind:
        raise CatalogError("Группа не подходит: выберите группу для товаров или для услуг.")
    if item.manual_cost is not None and item.manual_cost < 0:
        raise CatalogError("Себестоимость не может быть отрицательной.")
    item.save()
    if units is None:
        return item
    if item.for_sale and not any(u.get("for_sale", True) for u in units):
        raise CatalogError("Добавьте хотя бы одну единицу для продажи.")
    unit_ids = [_unit_id(u) for u in units]
    if len(set(map(str, unit_ids))) != len(unit_ids):
        raise CatalogError("Одна и та же единица указана дважды.")

    existing = {str(u.pk): u for u in item.units.all()}
    kept: set[str] = set()
    for data in units:
        current = existing.get(str(data.get("id"))) if data.get("id") else None
        if current is None:  # та же единица могла быть сохранена раньше без id
            current = next(
                (
                    u
                    for u in existing.values()
                    if str(u.unit_id) == str(getattr(data.get("unit"), "pk", data.get("unit")))
                ),
                None,
            )
        unit = current or ItemUnit(item=item)
        for field, value in data.items():
            if field == "id":
                continue
            if field == "unit":
                unit.unit_id = _unit_id(data)
            else:
                setattr(unit, field, value)
        if item.kind == Kind.SERVICE:
            unit.ratio = Decimal("1")
            unit.pricing = ItemUnit.Pricing.FIXED
        _check_unit(item, unit)
        unit.save()
        kept.add(str(unit.pk))
    for key, unit in existing.items():
        if key not in kept:
            unit.delete()
    return item


# --- Поиск -------------------------------------------------------------------------


def search_items(queryset: QuerySet[Item], text: str) -> QuerySet[Item]:
    """Поиск: слова — в названии; ещё точное совпадение артикула и штрихкода (товара и единиц)."""
    text = text.strip()
    exact = Q(article__iexact=text) | Q(barcode=text) | Q(units__barcode=text)
    by_words = Q()
    for word in text.split():
        by_words &= Q(name__icontains=word)
    return queryset.filter(exact | by_words).distinct()


def sale_units(item: Item) -> QuerySet[ItemUnit]:
    """Единицы, в которых товар продаётся — для счёта и медкарты (этап 3)."""
    return item.units.filter(for_sale=True)


# --- История цен -------------------------------------------------------------------


class PriceChange(TypedDict):
    date: Any
    user: str
    unit: str
    pricing: str
    price: str | None
    markup_percent: str | None


def price_history(item: Item, limit: int = 100) -> list[PriceChange]:
    """Изменения цен по единицам товара — из журнала аудита (новые сверху)."""
    records = (
        ItemUnit.history.model.objects.filter(item_id=item.pk)
        .select_related("history_user", "unit")
        .order_by("-history_date")[: limit * 3]
    )
    by_unit: dict[Any, list[Any]] = {}
    for record in records:
        by_unit.setdefault(record.id, []).append(record)

    changes: list[PriceChange] = []

    def key(record: Any) -> tuple[Any, ...]:
        return (record.pricing, record.price, record.markup_percent)

    for unit_records in by_unit.values():
        ordered = list(reversed(unit_records))  # от старых к новым
        for previous, record in zip([None, *ordered[:-1]], ordered, strict=True):
            if previous is not None and key(previous) == key(record):
                continue  # меняли не цену
            if record.history_type == "-":
                continue
            changes.append(
                {
                    "date": record.history_date,
                    "user": record.history_user.short_name if record.history_user else "",
                    "unit": record.unit.name,
                    "pricing": record.pricing,
                    "price": str(record.price) if record.price is not None else None,
                    "markup_percent": (
                        str(record.markup_percent) if record.markup_percent is not None else None
                    ),
                }
            )
    changes.sort(key=lambda change: change["date"], reverse=True)
    return changes[:limit]
