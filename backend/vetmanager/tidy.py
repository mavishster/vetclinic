"""Наведение порядка в прайсе после переноса из VetManager.

В VetManager каждая фасовка — отдельная позиция: «АКТИФЛОРА (1 саше)» и
«АКТИФЛОРА (уп 30 саше)». У нас это одна позиция с двумя единицами продажи,
поэтому такие строки предлагается объединить, а полные дубли — свести.

Ничего не меняется, пока пользователь не подтвердит: сначала предложение, потом применение.
"""

import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.db import transaction

from catalog import services as catalog
from catalog.models import Item, ItemUnit, Kind, Unit
from vetmanager import client

# Хвост названия с фасовкой: «(уп 30 саше)», «уп. 8 табл.», «№30», «x10», «10 табл.»
_PACK_WORDS = r"(?:уп|упак|упаковка|пач|пачка|блистер|бл|короб|кор|набор|№|n|x|х)"
# Только штучные фасовки. Вес и объём («2 кг», «75 г», «10 мл») — характеристика товара,
# а не упаковка: «Корм Hills 2 кг» не должен стать «2 корма».
_UNIT_WORDS = r"(?:саше|таб|табл|таблет\w*|капс\w*|амп\w*|шт|доз\w*|фл|флак\w*|пипет\w*|блистер\w*)"
_PACK_PATTERNS = [
    # «уп 30 саше», «упак. 8 табл.»
    re.compile(
        rf"\(?\s*{_PACK_WORDS}\.?\s*(\d+[.,]?\d*)\s*({_UNIT_WORDS})\.?\s*\)?\s*$", re.IGNORECASE
    ),
    # «(1 саше)», «10 табл.», «5 фл.»
    re.compile(rf"\(?\s*(\d+[.,]?\d*)\s*({_UNIT_WORDS})\.?\s*\)?\s*$", re.IGNORECASE),
    # «№30», «x30», «уп. 30»
    re.compile(rf"\(?\s*{_PACK_WORDS}\.?\s*(\d+)\s*\)?\s*$", re.IGNORECASE),
]
_UNIT_BY_WORD = {
    "саше": "саше",
    "таб": "таб.",
    "табл": "таб.",
    "таблетка": "таб.",
    "таблетки": "таб.",
    "таблеток": "таб.",
    "капс": "капс.",
    "капсула": "капс.",
    "капсул": "капс.",
    "амп": "амп.",
    "ампула": "амп.",
    "ампул": "амп.",
    "шт": "шт.",
    "доза": "доза",
    "дозы": "доза",
    "доз": "доза",
    "фл": "фл.",
    "флакон": "фл.",
    "флаконов": "фл.",
    "пипетка": "шт.",
    "пипеток": "шт.",
    "блистер": "блистер",
    "блистеров": "блистер",
}


@dataclass
class PackPart:
    """Одна из перенесённых позиций-фасовок."""

    item: Item
    quantity: Decimal | None  # сколько мелких единиц внутри (из названия)
    unit_name: str  # единица из названия: саше, таб.
    price: Decimal | None


def _clean(name: str) -> str:
    """Название без хвоста с фасовкой и лишних пробелов."""
    stripped = name
    for pattern in _PACK_PATTERNS:
        stripped = pattern.sub("", stripped)
    return " ".join(stripped.replace("()", " ").split()).strip(" ,.-—")


def _pack_of(name: str) -> tuple[Decimal | None, str]:
    """Что написано в хвосте названия: сколько и чего («уп 30 саше» → 30, «саше»)."""
    for pattern in _PACK_PATTERNS:
        found = pattern.search(name)
        if not found:
            continue
        quantity = Decimal(found.group(1).replace(",", "."))
        word = found.group(2).lower().rstrip(".") if found.lastindex and found.lastindex > 1 else ""
        return quantity, _UNIT_BY_WORD.get(word, word)
    return None, ""


def _find_unit(name: str) -> Unit | None:
    """Единица по названию — без учёта точек, пробелов и регистра."""
    simple = name.lower().replace("ё", "е").replace(".", "").replace(" ", "")
    return next(
        (
            unit
            for unit in Unit.objects.all()
            if unit.name.lower().replace("ё", "е").replace(".", "").replace(" ", "") == simple
        ),
        None,
    )


def _price(item: Item) -> Decimal | None:
    unit = item.units.filter(for_sale=True).first() or item.units.first()
    return unit.price if unit is not None else None


def _dose(name: str) -> str:
    """Дозировка внутри названия: «1 г», «50 мг/мл» — её нельзя путать с фасовкой."""
    found = re.findall(
        r"\d+[.,]?\d*\s*(?:мг|мкг|ме|г|мл)\s*(?:/\s*(?:мл|кг|доз\w*))?", name, re.IGNORECASE
    )
    return " ".join(part.lower().replace(" ", "") for part in found)


def documents_by_item() -> dict[str, int]:
    """Сколько раз каждая наша позиция встречается в счетах VetManager.

    Нужно, чтобы разбирать прайс прицельно: сначала то, что реально продают.
    Связь нет — не беда, просто не покажем число.
    """
    from vetmanager.models import Imported

    try:
        rows = client.fetch("invoiceDocument")
    except client.VetManagerError:
        return {}
    counts: Counter[str] = Counter(str(row.get("good_id") or "") for row in rows)
    ours = {link.external_id: str(link.target_id) for link in Imported.objects.filter(kind="item")}
    found: dict[str, int] = {}
    for external_id, count in counts.items():
        item_id = ours.get(external_id)
        if item_id:
            found[item_id] = found.get(item_id, 0) + count
    return found


def suggestions(with_documents: bool = True) -> list[dict[str, Any]]:
    """Что можно привести в порядок: дубли и фасовки одной позиции.

    Возвращает предложения — применять их или нет, решает пользователь.
    """
    documents = documents_by_item() if with_documents else {}
    items = list(
        Item.objects.filter(kind=Kind.GOODS, is_active=True)
        .select_related("base_unit", "group")
        .prefetch_related("units__unit")
    )
    groups: dict[tuple[str, str, Any], list[Item]] = {}
    for item in items:
        groups.setdefault((_clean(item.name).lower(), _dose(item.name), item.group_id), []).append(
            item
        )
    result = []
    for (base_name, _dosage, _group), found in groups.items():
        if len(found) < 2:
            continue
        parts = []
        for item in sorted(found, key=lambda i: i.name):
            quantity, unit_name = _pack_of(item.name)
            parts.append(
                PackPart(item=item, quantity=quantity, unit_name=unit_name, price=_price(item))
            )
        duplicates = all(part.quantity == parts[0].quantity for part in parts)
        result.append(
            {
                "kind": "duplicates" if duplicates else "packs",
                "name": _clean(found[0].name) or found[0].name,
                "base_name": base_name,
                "items": [
                    {
                        "id": str(part.item.pk),
                        "name": part.item.name,
                        "quantity": str(part.quantity) if part.quantity is not None else None,
                        # Единица самой позиции («упак.», «саше») — ею она и станет
                        # в объединённой позиции; слово из названия — подсказка.
                        "unit": part.item.base_unit.name,
                        "inner_unit": part.unit_name,
                        "price": str(part.price) if part.price is not None else None,
                        "used": bool(catalog.item_usage(part.item)),
                        "documents": documents.get(str(part.item.pk)),
                    }
                    for part in parts
                ],
            }
        )
    # Сначала то, что чаще встречается в счетах: с этого и стоит начинать разбор.
    for row in result:
        row["documents"] = sum(part["documents"] or 0 for part in row["items"])
    result.sort(key=lambda row: (-row["documents"], row["name"]))
    return result


@transaction.atomic
def merge(name: str, parts: list[dict[str, Any]]) -> Item:
    """Объединить позиции-фасовки в одну.

    parts — что оставить: [{"item": id, "quantity": сколько мелких единиц, "unit": название}].
    Мелкая фасовка становится единицей учёта, крупные — единицами продажи с количеством.
    Позиции, которые уже где-то использованы, не трогаются — об этом говорит ошибка.
    """
    chosen = []
    for part in parts:
        item = Item.objects.filter(pk=part.get("item")).select_related("base_unit").first()
        if item is None:
            raise catalog.CatalogError("Позиция не найдена — обновите страницу.")
        quantity = Decimal(str(part.get("quantity") or 1))
        if quantity <= 0:
            raise catalog.CatalogError(f"«{item.name}»: укажите, сколько единиц в упаковке.")
        chosen.append((item, quantity, str(part.get("unit") or item.base_unit.name)))
    if len(chosen) < 2:
        raise catalog.CatalogError("Для объединения нужны хотя бы две позиции.")
    used = [item.name for item, _, _ in chosen if catalog.item_usage(item)]
    if used:
        raise catalog.CatalogError(
            "Уже используются, объединять нельзя: " + ", ".join(used) + ". "
            "Объединяйте до того, как по позициям пройдут приходы и счета."
        )

    chosen.sort(key=lambda row: row[1])  # самая мелкая фасовка — первой
    main, base_quantity, base_unit_name = chosen[0]
    base_unit = _find_unit(base_unit_name) or main.base_unit
    units: list[catalog.UnitData] = []
    for item, quantity, unit_name in chosen:
        ratio = (quantity / base_quantity).quantize(Decimal("0.000001"))
        unit = base_unit if ratio == 1 else (_find_unit(unit_name) or item.base_unit)
        if any(row["unit"] == unit.pk for row in units):
            continue  # одинаковые фасовки (дубли) — одна единица
        source = item.units.filter(for_sale=True).first() or item.units.first()
        units.append(
            {
                "unit": unit.pk,
                "ratio": ratio,
                "pricing": source.pricing if source else ItemUnit.Pricing.FIXED,
                "price": source.price if source else None,
                "markup_percent": source.markup_percent if source else None,
                "price_min": source.price_min if source else None,
                "price_max": source.price_max if source else None,
                "barcode": source.barcode if source else "",
                "for_sale": True,
                "for_purchase": ratio > 1,
            }
        )
    main.name = (name or _clean(main.name) or main.name)[:200]
    main.base_unit = base_unit
    saved = catalog.save_item(main, units)
    for item, _, _ in chosen[1:]:
        catalog.delete_item(item)  # не использованы — проверено выше
    return saved


# --- Фасовки препаратов ----------------------------------------------------------------

# Единицы, в которых препарат приходит на склад, но отпускается поштучно.
# «Набор» и «саше» сюда не входят: набор продают целиком, саше — само по себе штука.
PACK_UNITS = {"упак.", "уп.", "упаковка", "коробка", "блистер", "фл.", "флакон", "туба"}
# Самое мелкое, чем отпускают: в этом и стоит вести остаток.
PIECE_UNITS = {"таб.", "капс.", "мл", "г", "мг", "доза", "амп.", "шт.", "саше"}
# Сколько мелких единиц в упаковке — из названия: «уп. 8 табл.», «фл 10мл», «100 мл».
_INSIDE = re.compile(
    r"(\d+[.,]?\d*)\s*(таб\w*|табл\w*|капс\w*|амп\w*|саше|доз\w*|мл|мг|г|шт)\.?\b", re.IGNORECASE
)
_INSIDE_UNIT = {
    "таб": "таб.",
    "табл": "таб.",
    "таблет": "таб.",
    "капс": "капс.",
    "амп": "амп.",
    "саше": "саше",
    "доз": "доза",
    "мл": "мл",
    "мг": "мг",
    "г": "г",
    "шт": "шт.",
}


def _inside_pack(name: str) -> tuple[Decimal | None, str]:
    """Что и сколько внутри упаковки по названию: «Ношпа уп. 8 табл.» → 8, «таб.»."""
    best: tuple[Decimal | None, str] = (None, "")
    for amount, word in _INSIDE.findall(name):
        key = word.lower().rstrip(".")
        unit = _INSIDE_UNIT.get(key[:5]) or _INSIDE_UNIT.get(key[:3]) or _INSIDE_UNIT.get(key)
        if unit:
            best = (Decimal(amount.replace(",", ".")), unit)
    return best


def _marked_ok() -> set[str]:
    """Позиции, которые пользователь пометил «не трогать»."""
    from vetmanager.models import Imported

    return set(Imported.objects.filter(kind="packaging_ok").values_list("external_id", flat=True))


def skip_packaging(item_id: str) -> None:
    """Пометить позицию разобранной: в списке фасовок больше не показывать."""
    from vetmanager.models import Imported

    item = Item.objects.filter(pk=item_id).first()
    if item is None:
        raise catalog.CatalogError("Позиция не найдена — обновите страницу.")
    Imported.objects.update_or_create(
        kind="packaging_ok", external_id=str(item.pk), defaults={"target_id": item.pk}
    )


def packaging_rows(with_documents: bool = True) -> list[dict[str, Any]]:
    """Препараты, у которых остаток ведётся упаковками, а отпускают поштучно.

    Такие позиции нужно поправить до переноса счетов: иначе продажа 2 мл спишет
    целый флакон. Для каждой подсказываем, сколько мелких единиц внутри.
    """
    documents = documents_by_item() if with_documents else {}
    marked_ok = _marked_ok()
    rows = []
    for item in (
        # Складской учёт не проверяем: при переносе отметка ставится по карточке
        # VetManager и у части препаратов не стоит, хотя остаток по ним ведут.
        Item.objects.filter(kind=Kind.GOODS, is_active=True)
        .select_related("base_unit")
        .prefetch_related("units__unit")
    ):
        base = item.base_unit.name
        if base not in PACK_UNITS:
            continue  # остаток уже ведётся в мелкой единице
        units = {unit.unit.name for unit in item.units.all()}
        if units & (PIECE_UNITS - {base}):
            continue  # поштучная единица уже заведена внутри позиции
        if str(item.pk) in marked_ok:
            continue  # пользователь сказал: эту позицию не трогать
        quantity, inside = _inside_pack(item.name)
        if inside == base:
            quantity, inside = None, ""
        rows.append(
            {
                "id": str(item.pk),
                "name": item.name,
                "base_unit": base,
                "quantity": str(quantity) if quantity is not None else None,
                "inside": inside,
                "price": str(_price(item) or ""),
                "documents": documents.get(str(item.pk), 0),
                "used": bool(catalog.item_usage(item)),
            }
        )
    rows.sort(key=lambda row: (-row["documents"], row["name"]))
    return rows


@transaction.atomic
def set_packaging(item_id: str, quantity: Decimal, inside: str, price: Decimal | None) -> Item:
    """Перевести позицию на поштучный учёт: остаток в мелкой единице, упаковка — закупка.

    Было: учёт в «упак.», продажа упаковкой. Стало: учёт в «таб.», упаковка = N таб.
    и помечена как единица закупки — приход по-прежнему оформляют упаковками.
    """
    item = Item.objects.filter(pk=item_id).select_related("base_unit").first()
    if item is None:
        raise catalog.CatalogError("Позиция не найдена — обновите страницу.")
    if quantity <= 1:
        raise catalog.CatalogError(
            f"«{item.name}»: укажите, сколько {inside or 'единиц'} в упаковке."
        )
    piece = _find_unit(inside)
    if piece is None:
        raise catalog.CatalogError(f"Нет единицы «{inside}» — заведите её в справочнике единиц.")
    if catalog.item_usage(item):
        raise catalog.CatalogError(
            f"«{item.name}» уже используется: единицу учёта можно менять, пока по позиции "
            "не было приходов и продаж."
        )
    pack = item.base_unit
    source = item.units.filter(unit=pack).first() or item.units.first()
    units: list[catalog.UnitData] = [
        {
            "unit": piece.pk,
            "ratio": Decimal("1"),
            "pricing": ItemUnit.Pricing.FIXED,
            "price": price,
            "for_sale": True,
            "for_purchase": False,
        },
        {
            "unit": pack.pk,
            "ratio": quantity,
            "pricing": source.pricing if source else ItemUnit.Pricing.FIXED,
            "price": source.price if source else None,
            "markup_percent": source.markup_percent if source else None,
            "barcode": source.barcode if source else "",
            "for_sale": True,
            "for_purchase": True,  # приход оформляют упаковками
        },
    ]
    item.base_unit = piece
    return catalog.save_item(item, units)
