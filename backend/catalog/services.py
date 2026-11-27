"""Каталог товаров и услуг: публичный вход модуля.

Отвечает за: товары, услуги, единицы, группы, цены и наценки, комбинации.

Другие модули обращаются к модулю только через функции этого файла.
Бизнес-правила живут здесь, а не в моделях и не в API (ENGINEERING.md).
"""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, TypedDict

from django.contrib.postgres.search import TrigramWordSimilarity
from django.db import transaction
from django.db.models import Case, F, IntegerField, Q, QuerySet, When

from catalog.models import (
    CombinationLine,
    DrugGroup,
    Item,
    ItemUnit,
    ItemUnitBarcode,
    Kind,
    Substance,
    Unit,
)
from core import services as core

D = Decimal


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
    extra_barcodes: list[str]


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


def _has_quantities(item: Item) -> bool:
    """Есть ли по позиции количества в единицах учёта: складские документы, движения,
    партии, строки счетов, минимумы и нормы. Пока их нет (прайс только заполняют, в том
    числе после переноса из другой программы) — единицу учёта можно исправить.

    Отметка «ведётся складской учёт» сама по себе ничего не значит: при переносе она
    ставится по карточке товара, ещё до первого прихода. Откатанные документы не считаются.
    """
    records = core.usage_records(item)
    return any(model._meta.app_label in {"inventory", "billing"} for model in records)


@transaction.atomic
def save_item(item: Item, units: list[UnitData] | None = None) -> Item:
    """Сохранить товар или услугу вместе с единицами (если переданы).

    Единицы, которых нет в переданном списке, удаляются (мягко).
    Цены меняются у существующих записей — так в журнале остаётся история цен.
    """
    item.name = item.name.strip()
    if not item.name:
        raise CatalogError("Укажите название.")
    expected_group_kind = Kind.SERVICE if item.kind == Kind.COMBO else item.kind
    if item.group.kind != expected_group_kind:
        raise CatalogError("Группа не подходит: выберите группу для товаров или для услуг.")
    if item.manual_cost is not None and item.manual_cost < 0:
        raise CatalogError("Себестоимость не может быть отрицательной.")
    if not item._state.adding:
        stored_unit = Item.objects.filter(pk=item.pk).values_list("base_unit_id", flat=True).first()
        if stored_unit is not None and stored_unit != item.base_unit_id and _has_quantities(item):
            raise CatalogError(
                "Единицу учёта нельзя менять после первого прихода или продажи: количества уже "
                "записаны в ней и пересчитались бы неверно. Если ошиблись — заведите новую позицию."
            )
    item.save()
    if units is None:
        return item
    if item.for_sale and not any(u.get("for_sale", True) for u in units):
        raise CatalogError("Добавьте хотя бы одну единицу для продажи.")
    unit_ids = [_unit_id(u) for u in units]
    for data in units if item.kind == Kind.GOODS else []:  # у услуги коэффициент всегда 1
        ratio = D(str(data.get("ratio", 1)))
        base = item.base_unit.name
        if str(_unit_id(data)) == str(item.base_unit_id) and ratio != 1:
            raise CatalogError(
                f"Единица учёта «{base}» всегда равна 1 {base}. Для упаковки выберите "
                f"другую единицу — например, «упак.» — и укажите, сколько в ней {base}."
            )
        if str(_unit_id(data)) != str(item.base_unit_id) and ratio == 1:
            # «таб.» = 1 «упак.» — почти всегда ошибка: 2 таблетки списались бы как 2 упаковки.
            name = Unit.objects.filter(pk=_unit_id(data)).values_list("name", flat=True).first()
            raise CatalogError(
                f"«{name}» не может быть равна 1 {base}: тогда продажа 1 {name} списывала бы "
                f"1 {base}. Если «{name}» меньше «{base}», выберите «меньше {base}» "
                f"и укажите, сколько {name} в одной {base}. "
                f"Для нового товара проще сделать единицей учёта «{name}», "
                f"а «{base}» — с количеством {name} в ней."
            )
    if len(set(map(str, unit_ids))) != len(unit_ids):
        repeated = next(u for u in unit_ids if list(map(str, unit_ids)).count(str(u)) > 1)
        name = Unit.objects.filter(pk=repeated).values_list("name", flat=True).first()
        raise CatalogError(f"Единица «{name}» указана в двух строках — оставьте одну.")

    existing = {str(u.pk): u for u in item.units.all()}
    # Сначала решаем, какие строки остаются, и убираем лишние: иначе смена единицы
    # на ту, что стояла у убранной строки, упиралась бы в запрет на повтор.
    matched: dict[int, ItemUnit] = {}
    for position, data in enumerate(units):
        current = existing.get(str(data.get("id"))) if data.get("id") else None
        if current is None:  # та же единица могла быть сохранена раньше без id
            current = next(
                (
                    u
                    for u in existing.values()
                    if str(u.unit_id) == str(getattr(data.get("unit"), "pk", data.get("unit")))
                    and u not in matched.values()
                ),
                None,
            )
        if current is not None:
            matched[position] = current
    kept: set[str] = {str(u.pk) for u in matched.values()}
    for key, stored in existing.items():
        if key not in kept:
            stored.delete()

    for position, data in enumerate(units):
        unit = matched.get(position) or ItemUnit(item=item)
        extra = data.get("extra_barcodes")
        for field, value in data.items():
            if field in ("id", "extra_barcodes"):
                continue
            if field == "unit":
                unit.unit_id = _unit_id(data)
            else:
                setattr(unit, field, value)
        if item.kind == Kind.SERVICE:
            unit.ratio = Decimal("1")
            unit.pricing = ItemUnit.Pricing.FIXED
        _check_unit(item, unit)
        unit.barcode = (unit.barcode or "").strip()
        _check_barcodes(unit, extra)
        unit.save()
        if extra is not None:
            _save_extra_barcodes(unit, extra)
    return item


# --- Штрихкоды (ADR-025) ----------------------------------------------------------


def _clean_codes(codes: list[str] | None) -> list[str]:
    result: list[str] = []
    for code in codes or []:
        code = str(code).strip()
        if code and code not in result:
            result.append(code)
    return result


def barcode_owner(code: str, exclude_unit: Any = None) -> str | None:
    """Чей это штрихкод: «Синулокс 50 мг (упак.)» — или None, если код свободен.

    Смотрит основной код единицы, дополнительные коды и код товара (верхнее поле).
    exclude_unit — единица, которую сейчас сохраняют (её собственные коды не мешают).
    """
    code = code.strip()
    if not code:
        return None
    exclude = getattr(exclude_unit, "pk", exclude_unit)
    units = ItemUnit.objects.select_related("item", "unit").filter(item__is_deleted=False)
    if exclude is not None:
        units = units.exclude(pk=exclude)
    unit = (
        units.filter(barcode=code).first()
        or units.filter(extra_barcodes__code=code, extra_barcodes__is_deleted=False).first()
    )
    if unit is not None:
        return f"{unit.item.name} ({unit.unit.name})"
    items = Item.objects.filter(barcode=code)
    if exclude is not None:
        items = items.exclude(units__pk=exclude)
    item = items.first()
    return item.name if item is not None else None


def _check_barcodes(unit: ItemUnit, extra: list[str] | None) -> None:
    """Новые коды единицы не должны принадлежать другим позициям: один код — одна упаковка.

    Проверяются только изменённые коды: старые совпадения (например, после переноса из
    другой программы) не мешают сохранить карточку — их показывает поиск по коду.
    """
    label = f"Единица «{unit.unit}»"
    stored_main = ""
    stored_extra: set[str] = set()
    if unit.pk and not unit._state.adding:
        stored_main = (
            ItemUnit.objects.filter(pk=unit.pk).values_list("barcode", flat=True).first() or ""
        )
        stored_extra = set(unit.extra_barcodes.values_list("code", flat=True))
    codes = _clean_codes(extra) if extra is not None else []
    if unit.barcode and unit.barcode in codes:
        raise CatalogError(f"{label}: код {unit.barcode} уже указан как основной.")
    new_codes = [c for c in codes if c not in stored_extra]
    if unit.barcode and unit.barcode != stored_main:
        new_codes.insert(0, unit.barcode)
    for code in new_codes:
        owner = barcode_owner(code, exclude_unit=unit.pk)
        if owner:
            raise CatalogError(
                f"{label}: штрихкод {code} уже записан у «{owner}». Один код — одна упаковка: "
                f"если это тот же товар, уберите код там; если другой — проверьте код на коробке."
            )


def _save_extra_barcodes(unit: ItemUnit, codes: list[str]) -> None:
    wanted = _clean_codes(codes)
    current = {b.code: b for b in unit.extra_barcodes.all()}
    for code, stored in current.items():
        if code not in wanted:
            stored.delete()
    for code in wanted:
        if code not in current:
            ItemUnitBarcode.objects.create(item_unit=unit, code=code)


def without_barcode(queryset: QuerySet[Item]) -> QuerySet[Item]:
    """Товары без единого штрихкода: ни у позиции, ни у её единиц (основного и дополнительных)."""
    coded = ItemUnit.objects.exclude(barcode="").values("item_id")
    extra = ItemUnitBarcode.objects.filter(item_unit__is_deleted=False).values("item_unit__item_id")
    return queryset.filter(kind=Kind.GOODS, barcode="").exclude(pk__in=coded).exclude(pk__in=extra)


@transaction.atomic
def assign_barcodes(unit_ids: Iterable[Any]) -> list[dict[str, str]]:
    """Присвоить внутренние штрихкоды («20…», ensure_barcode) единицам товаров, у которых
    своего нет. Единицы со штрихкодом не меняются. Возвращает [{item_unit, barcode, new}]."""
    result = []
    units = ItemUnit.objects.filter(pk__in=list(unit_ids), item__kind=Kind.GOODS)
    for unit in units.select_related("item").order_by("item__name", "-ratio"):
        new = not unit.barcode
        result.append({"item_unit": str(unit.pk), "barcode": ensure_barcode(unit), "new": new})
    return result


@transaction.atomic
def add_barcode(item_unit: ItemUnit, code: str) -> ItemUnit:
    """Привязать отсканированный код к единице товара: «это ещё один код этой упаковки».

    Нет основного кода — код становится основным, иначе — дополнительным.
    Код другой позиции не перехватывается — это ошибка (CatalogError).
    """
    code = code.strip()
    if not code:
        raise CatalogError("Пустой штрихкод.")
    if code == item_unit.barcode or item_unit.extra_barcodes.filter(code=code).exists():
        return item_unit
    owner = barcode_owner(code, exclude_unit=item_unit.pk)
    if owner:
        raise CatalogError(f"Штрихкод {code} уже записан у «{owner}».")
    if not item_unit.barcode:
        item_unit.barcode = code
        item_unit.save(update_fields=["barcode"])
    else:
        ItemUnitBarcode.objects.create(item_unit=item_unit, code=code)
    return item_unit


# --- Поиск -------------------------------------------------------------------------


def search_items(queryset: QuerySet[Item], text: str) -> QuerySet[Item]:
    """Поиск: слова — в названии; ещё точное совпадение артикула и штрихкода (товара и единиц)."""
    text = text.strip()
    exact = (
        Q(article__iexact=text)
        | Q(barcode=text)
        | Q(units__barcode=text)
        | Q(units__extra_barcodes__code=text, units__extra_barcodes__is_deleted=False)
    )
    by_words = Q()
    for word in text.split():
        by_words &= Q(name__icontains=word)
    return queryset.filter(exact | by_words).distinct()


def order_items(queryset: QuerySet[Item], ordering: str) -> QuerySet[Item]:
    """Сортировка списка прайса по колонке: name, group, unit, price, article
    («-» в начале — по убыванию). Пустые значения — в конце; при равенстве — по названию.

    unit — единица учёта товара (у услуг и комбинаций её нет — они в конце);
    price — наименьшая фиксированная цена среди единиц для продажи.
    """
    from django.db.models import Case, CharField, Min, Value, When
    from django.db.models.functions import Lower, NullIf

    key, descending = ordering.lstrip("-"), ordering.startswith("-")
    expressions: dict[str, Any] = {
        "name": Lower("name"),
        "group": Lower("group__name"),
        "article": NullIf(Lower("article"), Value("")),
        "unit": Case(
            When(kind=Kind.GOODS, then=Lower("base_unit__name")), default=None,
            output_field=CharField(),
        ),
        "price": Min("units__price", filter=Q(units__for_sale=True, units__is_deleted=False)),
    }  # fmt: skip
    if key not in expressions:
        return queryset
    queryset = queryset.annotate(sort_key=expressions[key])
    order = (
        F("sort_key").desc(nulls_last=True) if descending else F("sort_key").asc(nulls_last=True)
    )
    return queryset.order_by(order, "name", "pk")


# --- Подбор препаратов: с опечатками, аналоги по веществу и по группе -----------------

_LAYOUT = str.maketrans(
    "qwertyuiop[]asdfghjkl;'zxcvbnm,.`QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>~",
    "йцукенгшщзхъфывапролджэячсмитьбюёЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮЁ",
)
SUGGEST_LIMITS = {"name": 8, "substance": 6, "group": 6}
_FUZZY_MIN_LENGTH = 4  # короче — опечатки не ищем: слишком много случайных совпадений
_FUZZY_THRESHOLD = 0.4
_CONFIDENT = 0.6  # с такой похожестью считаем, что нашли именно этот препарат


class Suggestion(TypedDict):
    item: Item
    section: str  # name — по названию; substance — то же вещество; group — та же группа
    note: str  # для аналогов: какое вещество или группа совпали


def fix_layout(text: str) -> str:
    """«wtherfk» → «церукал»: текст, набранный в английской раскладке."""
    return text.translate(_LAYOUT)


def _by_name(queryset: QuerySet[Item], text: str, limit: int) -> tuple[list[Item], list[Item]]:
    """Совпадения по названию: сначала точные (все слова есть в названии, артикул, штрихкод),
    затем похожие — с опечатками (триграммы). Второй список — «уверенные» совпадения:
    к ним подбираются аналоги."""
    starts_first = Case(
        When(name__istartswith=text, then=0), default=1, output_field=IntegerField()
    )
    found: list[Item] = list(search_items(queryset, text).order_by(starts_first, "name")[:limit])
    confident: list[Item] = found[:3]
    if len(found) < limit and len(text) >= _FUZZY_MIN_LENGTH:
        fuzzy = (
            queryset.exclude(pk__in=[i.pk for i in found])
            .annotate(similarity=TrigramWordSimilarity(text, "name"))
            .filter(similarity__gte=_FUZZY_THRESHOLD)
            .order_by("-similarity", "name")
            .values_list("pk", "similarity")[: limit - len(found)]
        )
        similar = dict(fuzzy)
        by_pk = {item.pk: item for item in queryset.filter(pk__in=similar)}
        for index, (pk, similarity) in enumerate(
            sorted(similar.items(), key=lambda pair: -pair[1])
        ):
            found.append(by_pk[pk])
            # Точных совпадений нет — к лучшему похожему («цирукал» → «Церукал») тоже
            # подбираем аналоги: иначе опечатка лишала бы врача подсказок.
            if len(confident) < 3 and (similarity >= _CONFIDENT or (not confident and index == 0)):
                confident.append(by_pk[pk])
    return found, confident


def _named(model: Any, text: str, extra: Q | None = None) -> Any:
    """Справочник (вещества, группы) по названию — тоже с опечатками."""
    match = Q(name__icontains=text)
    if extra is not None:
        match |= extra
    queryset = model.objects.filter(is_active=True)
    if len(text) < _FUZZY_MIN_LENGTH:
        return queryset.filter(match)
    return queryset.annotate(similarity=TrigramWordSimilarity(text, "name")).filter(
        match | Q(similarity__gte=0.5)
    )


def suggest(queryset: QuerySet[Item], text: str) -> list[Suggestion]:
    """Подбор позиций для счёта и медкарты — одним списком из трёх разделов:

    1. по названию — в том числе с опечатками и в неверной раскладке;
    2. с тем же действующим веществом (аналоги найденного; полные аналоги — первыми);
       сюда же попадает всё с веществом, название которого набрали («маропитант»);
    3. из той же группы препаратов (или группы, которую набрали: «противорвотное»).
    """
    text = " ".join(text.split())
    if len(text) < 2:
        return []
    queryset = queryset.prefetch_related("substances", "drug_groups")
    found, confident = _by_name(queryset, text, SUGGEST_LIMITS["name"])
    if not found and not re.search("[а-яё]", text, re.IGNORECASE):
        fixed = fix_layout(text)  # ничего не нашли латиницей — пробуем как русскую раскладку
        if fixed != text:
            found, confident = _by_name(queryset, fixed, SUGGEST_LIMITS["name"])
            text = fixed if found else text
    result: list[Suggestion] = [{"item": item, "section": "name", "note": ""} for item in found]
    seen = {item.pk for item in found}

    # Вещества: у найденных препаратов и те, чьё название (или синоним) набрали.
    anchors = [set(s.pk for s in item.substances.all()) for item in confident]
    typed_substances = list(
        _named(Substance, text, Q(synonyms__icontains=text) | Q(latin_name__icontains=text))[:5]
    )
    substance_ids = (
        set().union(*anchors) | {s.pk for s in typed_substances}
        if (anchors or typed_substances)
        else set()
    )
    if substance_ids:
        candidates = list(
            queryset.filter(substances__in=substance_ids).exclude(pk__in=seen).distinct()[:60]
        )

        def closeness(item: Item) -> tuple[int, str]:
            own = {s.pk for s in item.substances.all()}
            full = any(
                own == anchor for anchor in anchors if anchor
            )  # полный аналог — тот же состав
            return (0 if full else 1, item.name.lower())

        for item in sorted(candidates, key=closeness)[: SUGGEST_LIMITS["substance"]]:
            shared = [s.name for s in item.substances.all() if s.pk in substance_ids]
            result.append({"item": item, "section": "substance", "note": ", ".join(shared)})
            seen.add(item.pk)

    # Группы: у найденных препаратов и те, чьё название набрали.
    group_ids = {g.pk for item in confident for g in item.drug_groups.all()}
    group_ids |= set(_named(DrugGroup, text).values_list("pk", flat=True)[:3])
    if group_ids:
        same_group = (
            queryset.filter(drug_groups__in=group_ids)
            .exclude(pk__in=seen)
            .distinct()
            .order_by("name")
        )
        for item in same_group[: SUGGEST_LIMITS["group"]]:
            shared = [g.name for g in item.drug_groups.all() if g.pk in group_ids]
            result.append({"item": item, "section": "group", "note": ", ".join(shared)})
    return result


def set_drug_info(item: Item, substances: list[Any] | None, drug_groups: list[Any] | None) -> None:
    """Вещества и группы препарата. Если группы не указаны, подставляются обычные группы
    выбранных веществ: достаточно выбрать вещество — группа появится сама."""
    if substances is not None:
        item.substances.set(substances)
    if drug_groups is not None:
        item.drug_groups.set(drug_groups)
    if not item.drug_groups.exists():
        typical = DrugGroup.objects.filter(substances__in=item.substances.all()).distinct()
        if typical:
            item.drug_groups.set(typical)


@transaction.atomic
def set_drug_info_bulk(
    items: list[Any], substances: list[Any], drug_groups: list[Any], replace: bool = False
) -> int:
    """Проставить вещества и группы сразу нескольким позициям прайса.

    По умолчанию добавляет к тому, что уже указано; replace — заменить целиком.
    Группы, как и в карточке, подставляются по веществам, если их не задали.
    """
    if not items:
        raise CatalogError("Выберите позиции.")
    if not substances and not drug_groups:
        raise CatalogError("Выберите действующее вещество или группу препарата.")
    for item in items:
        if replace:
            set_drug_info(item, substances or [], drug_groups or None)
            continue
        if substances:
            item.substances.add(*substances)
        if drug_groups:
            item.drug_groups.add(*drug_groups)
        elif substances and not item.drug_groups.exists():
            set_drug_info(item, None, None)  # подставит обычные группы веществ
    return len(items)


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


# --- Комбинации (ADR-017) ----------------------------------------------------------


class LineData(TypedDict, total=False):
    item_unit: Any  # ItemUnit или его id
    quantity: Decimal
    price_override: Decimal | None


class ExpandedLine(TypedDict):
    item_unit: ItemUnit
    quantity: Decimal
    price: Decimal | None  # цена за единицу: своя или по прайсу
    total: Decimal | None


@transaction.atomic
def save_combination(combination: Item, lines: list[LineData] | None = None) -> Item:
    """Сохранить комбинацию и её состав (если передан).

    В состав входят товары и услуги в единицах продажи; комбинации внутри
    комбинаций не допускаются — так состав всегда понятен.
    """
    combination.kind = Kind.COMBO
    if not combination.base_unit_id:
        combination.base_unit = Unit.objects.get_or_create(name="шт.")[0]
    save_item(combination)
    if lines is None:
        return combination
    if not lines:
        raise CatalogError("Добавьте в комбинацию хотя бы одну позицию.")
    prepared = []
    for position, data in enumerate(lines):
        value = data.get("item_unit")
        if value is None:
            raise CatalogError("В позиции комбинации не выбран товар или услуга.")
        item_unit = (
            value
            if isinstance(value, ItemUnit)
            else ItemUnit.objects.select_related("item").get(pk=value)
        )
        quantity = Decimal(str(data.get("quantity", 1)))
        override = data.get("price_override")
        if item_unit.item.kind == Kind.COMBO:
            raise CatalogError("Комбинацию нельзя вложить в другую комбинацию.")
        if not item_unit.for_sale:
            raise CatalogError(f"«{item_unit}» не продаётся в этой единице.")
        if quantity <= 0:
            raise CatalogError(f"«{item_unit}»: количество должно быть больше нуля.")
        if override is not None and override < 0:
            raise CatalogError(f"«{item_unit}»: цена не может быть отрицательной.")
        prepared.append(
            CombinationLine(
                combination=combination,
                item_unit=item_unit,
                quantity=quantity,
                price_override=override,
                position=position,
            )
        )
    combination.lines.all().delete()
    CombinationLine.objects.bulk_create(prepared)
    return combination


def expand_combination(combination: Item) -> list[ExpandedLine]:
    """Состав комбинации с ценами — для счёта: своя цена позиции или текущая по прайсу."""
    lines = combination.lines.select_related("item_unit__item__group", "item_unit__unit")
    expanded: list[ExpandedLine] = []
    for line in lines:
        price = line.price_override if line.price_override is not None else price_of(line.item_unit)
        total = (price * line.quantity).quantize(Decimal("0.01")) if price is not None else None
        expanded.append(
            {"item_unit": line.item_unit, "quantity": line.quantity, "price": price, "total": total}
        )
    return expanded


def combination_price(combination: Item) -> Decimal | None:
    """Цена комбинации — сумма позиций. Неизвестна, если неизвестна цена хотя бы одной."""
    totals = [line["total"] for line in expand_combination(combination)]
    if any(total is None for total in totals):
        return None
    return sum((t for t in totals if t is not None), Decimal("0"))


def reset_combination_prices(combination: Item) -> None:
    """Сбросить свои цены позиций — дальше они идут по текущему прайсу."""
    combination.lines.update(price_override=None)


# Виды профилактики, где процедура — это работа врача, а не препарат: стерилизацию
# и чипирование записывают услугой. Для остальных в записи выбирают препарат,
# а услугу врач добавляет в счёт отдельно.
PROCEDURE_PREVENTIONS = ("sterilization", "chipping")


def preparations(prevention_kind: str) -> QuerySet[Item]:
    """Чем делают профилактику этого вида: своя отметка позиции или отметка её группы.

    Вакцинация, дегельминтизация и обработка от эктопаразитов — это препараты
    (Нобивак, Дронтал, Бравекто). Стерилизация и чипирование — услуги: препарата
    там нет, и в записи указывают саму процедуру.
    """
    kind = Kind.SERVICE if prevention_kind in PROCEDURE_PREVENTIONS else Kind.GOODS
    return (
        Item.objects.filter(is_active=True, kind=kind)
        .filter(
            Q(prevention_kind=prevention_kind)
            | Q(prevention_kind="", group__prevention_kind=prevention_kind)
        )
        .order_by("name")
    )


def prevention_kind_of(item: Item) -> str:
    """Вид профилактики позиции: свой или группы ("" — не относится к профилактике)."""
    return item.prevention_kind or item.group.prevention_kind


def item_units(ids: list[Any]) -> QuerySet[ItemUnit]:
    """Единицы товаров по id — например, отмеченные в тексте медкарты."""
    return ItemUnit.objects.filter(pk__in=ids).select_related("item", "unit")


def item_units_of(item_ids: Iterable[Any]) -> QuerySet[ItemUnit]:
    """Все единицы товаров — для выбора единицы в строке (упак., фл., таб.); крупные первыми."""
    return (
        ItemUnit.objects.filter(item_id__in=list(item_ids))
        .select_related("unit", "item__base_unit")
        .order_by("item_id", "-ratio")
    )


def mark_stock_tracked(item: Item) -> None:
    """Склад начал вести учёт товара (первый выполненный приход)."""
    if not item.stock_tracked:
        item.stock_tracked = True
        item.save(update_fields=["stock_tracked"])


def combinations_with(item: Item) -> QuerySet[Item]:
    """Комбинации, в составе которых есть позиция — проверить, прежде чем менять или убирать её."""
    return Item.objects.filter(kind=Kind.COMBO, lines__item_unit__item=item).distinct()


def removed_units(item: Item) -> QuerySet[ItemUnit]:
    """Убранные единицы товара — посмотреть, какие были и по какой цене."""
    return ItemUnit.all_objects.filter(item=item, is_deleted=True).select_related("unit")


def get_item_unit(pk: Any) -> ItemUnit | None:
    return ItemUnit.objects.select_related("item__group", "unit").filter(pk=pk).first()


def find_by_barcode(code: str) -> ItemUnit | None:
    """Позиция по штрихкоду: основной код единицы (упаковки), дополнительный код единицы,
    потом — код товара (верхнее поле карточки; ведёт к единице учёта)."""
    code = code.strip()
    if not code:
        return None
    units = ItemUnit.objects.select_related("item", "unit").filter(item__is_deleted=False)
    unit = units.filter(barcode=code).order_by("created_at").first()
    if unit is None:
        unit = units.filter(extra_barcodes__code=code, extra_barcodes__is_deleted=False).first()
    if unit is not None:
        return unit
    item = Item.objects.filter(barcode=code).first()
    if item is None:
        return None
    return item.units.select_related("item", "unit").filter(unit=item.base_unit).first() or (
        item.units.select_related("item", "unit").first()
    )


def base_item_unit(item: Any) -> ItemUnit | None:
    """Единица товара, совпадающая с единицей учёта (коэффициент 1), иначе — первая."""
    units = ItemUnit.objects.select_related("item", "unit").filter(item=item)
    return units.filter(unit_id=F("item__base_unit_id")).first() or units.order_by("ratio").first()


def _ean13_check_digit(first12: str) -> str:
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(first12))
    return str((10 - total % 10) % 10)


def ensure_barcode(item_unit: ItemUnit) -> str:
    """Штрихкод единицы для этикетки: свой или внутренний EAN-13.

    Внутренние коды начинаются с «20» — этот диапазон EAN-13 отведён для кодов внутри
    организации и не пересекается с кодами производителей. Код сохраняется в единице —
    при сканировании этикетки товар найдётся.
    """
    if item_unit.barcode:
        return item_unit.barcode
    while True:
        first12 = f"20{core.next_value('internal_barcode'):010d}"
        code = first12 + _ean13_check_digit(first12)
        taken = (
            ItemUnit.objects.filter(barcode=code).exists()
            or Item.objects.filter(barcode=code).exists()
            or ItemUnitBarcode.objects.filter(code=code).exists()
        )
        if not taken:
            break
    item_unit.barcode = code
    item_unit.save(update_fields=["barcode"])
    return code


def get_item(pk: Any) -> Item | None:
    return Item.objects.select_related("group", "base_unit").filter(pk=pk).first()


def default_responsible(item: Item) -> list[Any]:
    """Ответственные сотрудники услуги (в порядке добавления)."""
    return list(item.responsible.filter(is_active=True))


def sale_unit(item: Any) -> ItemUnit | None:
    """Единица для продажи по умолчанию: совпадающая с единицей учёта, иначе первая продаваемая."""
    units = ItemUnit.objects.filter(item=item, for_sale=True)
    return units.filter(unit_id=F("item__base_unit_id")).first() or units.order_by("ratio").first()


def item_usage(item: Item) -> list[tuple[str, int]]:
    """Где используется позиция прайса (и её единицы): счета, склад, медкарта, комбинации…

    Собственные части позиции не считаются: её единицы и строки самой комбинации.
    """

    def own(model: Any, field: str) -> bool:
        return model is ItemUnit or (model is CombinationLine and field == "combination")

    # Строка счёта ссылается и на позицию, и на её единицу — считаем каждую запись один раз.
    records = core.usage_records(item, skip=own)
    for unit in ItemUnit.all_objects.filter(item=item):
        for model, pks in core.usage_records(unit).items():
            records.setdefault(model, set()).update(pks)
    totals = {str(model._meta.verbose_name_plural): len(pks) for model, pks in records.items()}
    return sorted(totals.items(), key=lambda pair: -pair[1])


@transaction.atomic
def delete_item(item: Item) -> None:
    """Удалить позицию, которой ещё нигде не пользовались. Иначе — CatalogError со списком мест:
    такую позицию можно только сделать неактивной (история сохраняется)."""
    used = item_usage(item)
    if used:
        places = ", ".join(f"{title} — {count}" for title, count in used)
        raise CatalogError(
            f"«{item}» уже используется: {places}. Удалить нельзя — снимите галочку «Активен»: "
            "позиция перестанет предлагаться для выбора, а история сохранится."
        )
    CombinationLine.objects.filter(combination=item).delete()
    item.units.all().delete()
    item.delete()


# --- Остаток словами: «5,25 упак. / 5 упак. 2 таб.» -------------------------------


def _number(value: Decimal) -> str:
    """5 вместо 5.000, 5,25 вместо 5.250 (до трёх знаков)."""
    text = format(value.quantize(D("0.001")).normalize(), "f")
    if text in ("-0", "0E-3"):
        text = "0"
    return text.replace(".", ",")


def _qty_text(qty: Decimal, base: str, units: list[tuple[Decimal, str]]) -> str:
    """Остаток в единицах учёта → текст для человека.

    Сначала точное количество в той единице, в которой ведётся склад, затем — то же
    крупными единицами: «437 мл (4 фл. 37 мл)», «42 таб. (5 упак. 2 таб.)».
    Если крупной единицы нет или разбивка ничего не добавляет — просто «12 шт.».
    """
    ratios = sorted({(ratio, name) for ratio, name in units if ratio > 0})
    if len({ratio for ratio, _ in ratios}) < 2:
        if ratios and ratios[0][0] != 1:
            ratio, name = ratios[0]
            return f"{_number(qty / ratio)} {name}"
        return f"{_number(qty)} {base}"
    piece_ratio, piece = ratios[0]
    pack_ratio, pack = ratios[-1]
    main = f"{_number(qty / piece_ratio)} {piece}" if piece_ratio != 1 else f"{_number(qty)} {base}"
    sign = "-" if qty < 0 else ""
    whole = int((abs(qty) / pack_ratio).to_integral_value(rounding="ROUND_FLOOR"))
    pieces = (abs(qty) - whole * pack_ratio) / piece_ratio
    nearest = pieces.to_integral_value(rounding=ROUND_HALF_UP)
    if abs(pieces - nearest) < D("0.02"):
        pieces = nearest
    per_pack = pack_ratio / piece_ratio
    if pieces >= per_pack:  # округление дало целую упаковку
        whole, pieces = whole + 1, pieces - per_pack
    if not whole:
        return main  # меньше одной упаковки — разбивка ничего не добавит
    parts = [f"{whole} {pack}"]
    if pieces:
        parts.append(f"{_number(pieces)} {piece}")
    return f"{main} ({sign}{' '.join(parts)})"


def qty_formatter(item_ids: Iterable[Any]) -> Callable[[Any, Decimal | None], str]:
    """Функция «товар, остаток в единицах учёта → текст» для многих товаров сразу (один запрос
    единиц на всех). Пример: «42 таб. (5 упак. 2 таб.)»."""
    ids = {getattr(i, "pk", i) for i in item_ids}
    bases = dict(Item.objects.filter(pk__in=ids).values_list("pk", "base_unit__name"))
    units: dict[Any, list[tuple[Decimal, str]]] = {}
    for item_id, ratio, name in ItemUnit.objects.filter(item_id__in=ids).values_list(
        "item_id", "ratio", "unit__name"
    ):
        units.setdefault(item_id, []).append((ratio, name))

    def text(item: Any, qty: Decimal | None) -> str:
        key = getattr(item, "pk", item)
        if isinstance(key, str):
            key = next((k for k in bases if str(k) == key), key)
        return _qty_text(D(str(qty or 0)), bases.get(key, ""), units.get(key, []))

    return text


def qty_text(item: Any, qty: Decimal | None) -> str:
    """Остаток одного товара словами (см. qty_formatter)."""
    return qty_formatter([item])(item, qty)


# --- Объединение позиций (ADR-026) -------------------------------------------------


@dataclass
class ItemMerge:
    """Что во что переводится при объединении позиций.

    units — старая единица → единица, которая останется у основной позиции (та же
    упаковка; количество «в этой единице» в строках не меняется). factors — во сколько раз
    меняется количество «в единицах учёта» у записей каждой позиции: была единица учёта
    «упак.», стала «таб.» при 4 таб. в упаковке → 4.
    """

    main: Item
    items: list[Item]  # все объединяемые, основная — первой
    units: dict[Any, Any]
    owners: dict[Any, Any]  # единица → позиция, которой она принадлежала
    factors: dict[Any, Decimal]
    dry_run: bool

    def changes_item(self, item_id: Any) -> bool:
        return item_id != self.main.pk or self.factors[item_id] != 1


class MergeUnit(TypedDict):
    item_unit: Any
    unit: Any
    ratio: Decimal


def repoint_rows(
    model: Any,
    merge: ItemMerge,
    item_field: str | None = None,
    unit_field: str | None = None,
    qty_fields: tuple[str, ...] = (),
) -> int:
    """Перевести записи чужого модуля на основную позицию: позицию, единицу и количества
    в единицах учёта (× factor). Возвращает, сколько записей затронуто.

    Сначала собираются номера записей, потом обновляются: запись, переведённая на
    единицу-«хранителя», не пересчитывается второй раз.
    """
    manager = model._base_manager
    plan: list[tuple[list[Any], dict[str, Any]]] = []

    def updates(item_id: Any, keeper: Any = None) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if item_field:
            result[f"{item_field}_id"] = merge.main.pk
        if keeper is not None and unit_field:
            result[f"{unit_field}_id"] = keeper
        factor = merge.factors[item_id]
        if factor != 1:
            result.update({name: F(name) * factor for name in qty_fields})
        return result

    if unit_field:
        for old, keeper in merge.units.items():
            owner = merge.owners[old]
            if old == keeper and not merge.changes_item(owner):
                continue
            pks = list(manager.filter(**{unit_field: old}).values_list("pk", flat=True))
            if pks:
                plan.append((pks, updates(owner, keeper)))
    if item_field:
        rows = manager.all()
        if unit_field:
            rows = rows.filter(**{f"{unit_field}__isnull": True})
        for item in merge.items:
            if not merge.changes_item(item.pk):
                continue
            pks = list(rows.filter(**{item_field: item.pk}).values_list("pk", flat=True))
            if pks:
                plan.append((pks, updates(item.pk)))
    total = sum(len(pks) for pks, _ in plan)
    if not merge.dry_run:
        for pks, values in plan:
            manager.filter(pk__in=pks).update(**values)
    return total


def _merge_plan(
    main_id: Any, item_ids: list[Any], base_unit_id: Any, units: list[MergeUnit]
) -> tuple[ItemMerge, dict[Any, tuple[Any, Decimal]]]:
    """Проверить план объединения. Возвращает ItemMerge и для каждой единицы-«хранителя» —
    (единица, количество в единице учёта)."""
    ids = list(dict.fromkeys(str(i) for i in item_ids))
    if str(main_id) not in ids:
        ids.insert(0, str(main_id))
    found = {str(i.pk): i for i in Item.objects.filter(pk__in=ids).select_related("base_unit")}
    if len(found) != len(ids):
        raise CatalogError("Позиция не найдена — обновите страницу.")
    if len(ids) < 2:
        raise CatalogError("Отметьте хотя бы две позиции.")
    items = [found[str(main_id)]] + [found[i] for i in ids if i != str(main_id)]
    if len({i.kind for i in items}) > 1 or items[0].kind == Kind.COMBO:
        raise CatalogError("Объединять можно товары с товарами или услуги с услугами.")
    base_unit = Unit.objects.filter(pk=base_unit_id).first()
    if base_unit is None:
        raise CatalogError("Выберите единицу учёта.")
    base = base_unit.name

    stored = {
        str(u.pk): u for u in ItemUnit.objects.filter(item__in=items).select_related("unit", "item")
    }
    plan = {str(row.get("item_unit")): row for row in units}
    missing = [u for key, u in stored.items() if key not in plan]
    if missing:
        raise CatalogError(f"Не указано, чем станет «{missing[0].unit}» у «{missing[0].item}».")
    targets: dict[Any, Decimal] = {}  # единица → количество в единице учёта
    target_of: dict[str, Any] = {}  # старая единица → во что превращается
    factors: dict[Any, Decimal] = {}
    for key, unit in stored.items():
        row = plan[key]
        ratio = D(str(row.get("ratio") or 0))
        target = Unit.objects.filter(pk=row.get("unit")).first()
        label = f"«{unit.item}» ({unit.unit})"
        if target is None or ratio <= 0:
            raise CatalogError(f"{label}: выберите единицу и укажите, сколько в ней {base}.")
        if target.pk == base_unit.pk and ratio != 1:
            raise CatalogError(f"{label}: единица учёта «{base}» всегда равна 1 {base}.")
        if target.pk != base_unit.pk and ratio == 1:
            raise CatalogError(
                f"{label}: «{target}» не может быть равна 1 {base} — укажите, больше она или "
                f"меньше «{base}» и сколько (например, «меньше {base}», в 1 {base} — 4 {target})."
            )
        if target.pk in targets and targets[target.pk] != ratio:
            raise CatalogError(
                f"«{target}» указана с разным количеством: {_num(targets[target.pk])} и "
                f"{_num(ratio)} {base}. Для одной из упаковок выберите другую единицу."
            )
        targets[target.pk] = ratio
        target_of[key] = target.pk
        factor = ratio / unit.ratio
        previous = factors.setdefault(unit.item_id, factor)
        if abs(previous - factor) > D("0.000001") * previous:
            raise CatalogError(
                f"«{unit.item}»: количества единиц не сходятся между собой — проверьте, сколько "
                f"{base} в каждой её единице."
            )
    for item in items:
        factors.setdefault(item.pk, D("1"))  # у позиции нет единиц — пересчитывать нечего

    # Хранитель единицы: своя единица основной позиции, иначе — первая по порядку позиций.
    order = {item.pk: n for n, item in enumerate(items)}
    keepers: dict[Any, ItemUnit] = {}
    for unit in sorted(stored.values(), key=lambda u: (order[u.item_id], u.ratio)):
        keepers.setdefault(target_of[str(unit.pk)], unit)
    unit_map = {u.pk: keepers[target_of[key]].pk for key, u in stored.items()}
    owners = {u.pk: u.item_id for u in stored.values()}
    keeper_plan = {keeper.pk: (unit_id, targets[unit_id]) for unit_id, keeper in keepers.items()}
    merge = ItemMerge(
        main=items[0],
        items=items,
        units=unit_map,
        owners=owners,
        factors=factors,
        dry_run=True,
    )
    merge.main.base_unit = base_unit
    return merge, keeper_plan


def _num(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _merge_own(merge: ItemMerge) -> list[tuple[str, int]]:
    """Свои записи каталога: строки комбинаций (единица)."""
    lines = repoint_rows(CombinationLine, merge, unit_field="item_unit")
    return [("строки комбинаций", lines)] if lines else []


@transaction.atomic
def merge_items(
    main_id: Any,
    item_ids: list[Any],
    name: str,
    base_unit_id: Any,
    units: list[MergeUnit],
    dry_run: bool = True,
) -> dict[str, Any]:
    """Объединить позиции прайса в одну, в том числе уже использованные (ADR-026).

    Все записи (счета, медкарта, черновики склада, комбинации, связи с VetManager)
    переводятся на основную позицию; количества в единицах учёта пересчитываются.
    Остатки и движения склада не пересчитываются — с ними объединять нельзя.
    dry_run — только посчитать, что изменится.
    """
    from core.events import items_merging

    merge, keeper_plan = _merge_plan(main_id, item_ids, base_unit_id, units)
    changes: list[tuple[str, int]] = _merge_own(merge)
    for _receiver, result in items_merging.send(sender=Item, merge=merge):
        changes.extend(list(result or []))
    summary = {
        "changes": [{"title": t, "count": c} for t, c in changes if c],
        "units": [
            {"unit": Unit.objects.get(pk=unit_id).name, "ratio": _num(ratio)}
            for unit_id, ratio in sorted(keeper_plan.values(), key=lambda row: row[1])
        ],
    }
    if dry_run:
        return summary

    merge.dry_run = False
    main = merge.main
    _merge_own(merge)
    items_merging.send(sender=Item, merge=merge)

    keepers = set(keeper_plan)
    stored = ItemUnit.objects.filter(item__in=merge.items)
    for unit in stored.exclude(pk__in=keepers):
        keeper_id = merge.units[unit.pk]
        ItemUnitBarcode.objects.filter(item_unit=unit).update(item_unit_id=keeper_id)
        if unit.barcode:
            keeper = ItemUnit.objects.get(pk=keeper_id)
            if unit.barcode != keeper.barcode and not keeper.barcode:
                keeper.barcode = unit.barcode
                keeper.save(update_fields=["barcode"])
            elif unit.barcode != keeper.barcode:
                ItemUnitBarcode.objects.create(item_unit=keeper, code=unit.barcode)
            unit.barcode = ""
            unit.save(update_fields=["barcode"])
        unit.delete()
    # Единицы могут меняться местами: «коробка» основной становится «блоком», а «коробкой»
    # становится единица дубля. Сохраняя по одной, база на миг увидела бы две одинаковые
    # единицы у позиции (уникальность — среди неудалённых). Поэтому сначала все меняющиеся
    # единицы выводятся из-под проверки, потом получают итоговые значения.
    moving = [
        keeper.pk
        for keeper in ItemUnit.objects.filter(pk__in=keepers)
        if keeper.item_id != main.pk or str(keeper.unit_id) != str(keeper_plan[keeper.pk][0])
    ]
    ItemUnit.all_objects.filter(pk__in=moving).update(is_deleted=True)
    for keeper in ItemUnit.all_objects.filter(pk__in=keepers):
        unit_id, ratio = keeper_plan[keeper.pk]
        keeper.item = main
        keeper.unit_id = unit_id
        keeper.ratio = ratio
        keeper.is_deleted = False
        keeper.save()

    others = merge.items[1:]
    main.name = (name or main.name).strip()[:255]
    if not main.name:
        raise CatalogError("Укажите название.")
    if main.manual_cost is not None:
        main.manual_cost = (main.manual_cost / merge.factors[main.pk]).quantize(D("0.01"))
    else:
        donor = next((o for o in others if o.manual_cost is not None), None)
        if donor is not None and donor.manual_cost is not None:
            main.manual_cost = (donor.manual_cost / merge.factors[donor.pk]).quantize(D("0.01"))
    main.stock_tracked = any(i.stock_tracked for i in merge.items)
    main.save()
    for other in others:
        main.substances.add(*other.substances.all())
        main.drug_groups.add(*other.drug_groups.all())
        main.responsible.add(*other.responsible.all())
        other.is_active = False
        other.save(update_fields=["is_active"])
        other.delete()
    summary["item"] = str(main.pk)
    return summary
