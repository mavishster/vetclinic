"""Ввод остатков по списку из старого файла склада.

Клиника вела склад в Excel: штрихкод, наименование, срок годности, единица, количество.
Количества там устаревшие, но сам список — готовый перечень «что искать на полке».
Файл загружается в черновик инвентаризации: каждая строка заранее сопоставлена с
прайсом (по штрихкоду, потом по названию), на полке строку отмечают, вписывают
фактическое количество — и она становится строкой документа. Неотмеченное видно сразу.

Штрихкоды из файла можно записать в прайс тем позициям, что совпали по названию:
дальше товар находится сканером везде — в продаже, приходе, перемещении.
"""

import difflib
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from django.db import transaction

from catalog import services as catalog
from catalog.models import Item, ItemUnit, Kind
from core import tables
from inventory.models import StockDocument

MAX_ROWS = 5000

# Заголовки старых файлов клиники — с опечатками («Штрикод», «Наиминование»).
COLUMNS: dict[str, tuple[str, ...]] = {
    "barcode": ("штрихкод", "штрикод", "штрих-код", "штрих код", "ean", "barcode"),
    "name": ("наименование", "наиминование", "название", "номенклатура", "товар"),
    "expiry": ("срок годности", "годен до", "срок", "дата"),
    "unit": ("единица", "ед. изм.", "ед.изм.", "ед", "ед."),
    "quantity": ("на складе", "остаток", "количество", "кол-во"),
}

# Единица из файла → единицы прайса, которые ей подходят (без точек и регистра).
UNIT_ALIASES: dict[str, tuple[str, ...]] = {
    "уп": ("упак", "уп", "упаковка"),
    "фл": ("фл", "флакон"),
    "шт": ("шт",),
    "шт/уп": ("шт",),
    "амп": ("амп", "ампула"),
    "доз": ("доза", "доз"),
    "тюб": ("туба", "тюбик", "тюб"),
    "банка": ("банка", "бан"),
    "пласт": ("пласт", "пластина", "блистер"),
}

SECTION = re.compile(r"^(поступление|приход)\b", re.IGNORECASE)
SIMILAR_CUTOFF = 0.82


class ChecklistError(Exception):
    """Файл не удалось разобрать. Текст — для пользователя."""


@dataclass
class Row:
    row: int  # номер строки в файле — по нему строка документа помнит, откуда она
    name: str
    barcode: str = ""
    expiry: str | None = None
    unit_text: str = ""
    qty_file: str | None = None  # сколько было по файлу — подсказка, а не остаток
    section: str = ""  # «Поступление 03.07.2026» — заголовок над строкой в файле
    match: str = ""  # barcode | name | similar | manual | "" (не нашлось)
    item: str | None = None
    item_unit: str | None = None
    item_name: str = ""
    unit_name: str = ""
    base_unit: str = ""
    ratio: str = "1"
    candidates: list[dict[str, str]] = field(default_factory=list)


def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"(\d),(\d)", r"\1.\2", text)
    text = re.sub(r"[^\w.%]+", " ", text)
    text = re.sub(r"(\d)\s+(мл|мг|г|кг|см|мкг|ед)\b", r"\1\2", text)
    return " ".join(text.replace(" .", " ").split())


def _plain(unit_name: str) -> str:
    return unit_name.lower().replace(".", "").strip()


def _barcode(text: str) -> str:
    code = re.sub(r"\D", "", text)
    return code if len(code) >= 8 else ""  # «0», «4» — не штрихкоды


def _expiry(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        parsed = tables.parse_date(str(value or ""))
    except ValueError:
        return None  # «?» и прочее — срок не указан
    return parsed.isoformat() if parsed else None


def _columns(table: list[list[Any]]) -> tuple[int, dict[str, int]]:
    """Строка заголовков и колонки. В файлах клиники колонка «Количество» хранит
    единицу (уп, фл), а количество — в «На складе»: смотрим и на содержимое."""
    for index, raw in enumerate(table[:15]):
        mapping = tables.header_map(raw, COLUMNS)
        if "name" not in mapping:
            continue
        headers = {str(value or "").strip().lower(): i for i, value in enumerate(raw)}
        quantity = headers.get("количество")
        on_hand = headers.get("на складе")
        if quantity is not None and on_hand is not None:
            sample = [r[quantity] for r in table[index + 1 : index + 40] if len(r) > quantity]
            texts = [v for v in sample if isinstance(v, str) and v.strip()]
            if len(texts) > len(sample) // 2:  # в «Количестве» — слова: это единица
                mapping["unit"], mapping["quantity"] = quantity, on_hand
        return index, mapping
    raise ChecklistError("Не нашли строку заголовков с колонкой «Наименование».")


class _Catalog:
    """Товары прайса для сопоставления — загружаются один раз на файл."""

    def __init__(self) -> None:
        self.items = list(
            Item.objects.filter(kind=Kind.GOODS, is_active=True).select_related("base_unit")
        )
        self.by_name: dict[str, Item] = {}
        for item in self.items:
            self.by_name.setdefault(normalize(item.name), item)
        self.names = list(self.by_name)
        units = ItemUnit.objects.select_related("unit").filter(item__in=self.items)
        self.units: dict[Any, list[ItemUnit]] = {}
        for unit in units:
            self.units.setdefault(unit.item_id, []).append(unit)

    def unit_for(self, item: Item, unit_text: str) -> ItemUnit | None:
        """Единица позиции, соответствующая единице из файла; иначе — единица учёта."""
        units = self.units.get(item.pk, [])
        wanted = UNIT_ALIASES.get(_plain(unit_text), (_plain(unit_text),))
        for unit in units:
            if unit_text and _plain(unit.unit.name) in wanted:
                return unit
        return next(
            (u for u in units if u.unit_id == item.base_unit_id and u.ratio == 1),
            units[0] if units else None,
        )


def _fill(row: Row, unit: ItemUnit, how: str) -> None:
    row.match, row.item, row.item_unit = how, str(unit.item_id), str(unit.pk)
    row.item_name, row.unit_name = unit.item.name, unit.unit.name
    row.base_unit = unit.item.base_unit.name
    row.ratio = format(unit.ratio.normalize(), "f")


def _match(row: Row, known: _Catalog) -> None:
    if row.barcode:
        unit = catalog.find_by_barcode(row.barcode)
        if unit is not None and unit.item.kind == Kind.GOODS:
            _fill(row, unit, "barcode")
            return
    key = normalize(row.name)
    item = known.by_name.get(key)
    if item is not None:
        unit = known.unit_for(item, row.unit_text)
        if unit is not None:
            _fill(row, unit, "name")
            return
    close = difflib.get_close_matches(key, known.names, n=3, cutoff=SIMILAR_CUTOFF)
    for name in close:
        candidate = known.by_name[name]
        unit = known.unit_for(candidate, row.unit_text)
        if unit is None:
            continue
        row.candidates.append(
            {"item_unit": str(unit.pk), "item_name": candidate.name, "unit_name": unit.unit.name}
        )
    if row.candidates:
        # Похожее — только подсказка: строку отметят на полке, этим и подтвердят.
        best = ItemUnit.objects.select_related("item__base_unit", "unit")
        _fill(row, best.get(pk=row.candidates[0]["item_unit"]), "similar")


def parse(content: bytes, filename: str) -> list[dict[str, Any]]:
    """Строки файла, сопоставленные с прайсом. Ничего не сохраняет."""
    try:
        table = tables.read_table(content, filename)
    except tables.TableError as error:
        raise ChecklistError(str(error)) from error
    header, mapping = _columns(table)
    known = _Catalog()
    rows: list[Row] = []
    section = ""
    for number, raw in enumerate(table[header + 1 :], start=header + 2):
        name = tables.text(raw, mapping, "name")
        code = _barcode(tables.text(raw, mapping, "barcode"))
        unit_text = tables.text(raw, mapping, "unit")
        quantity_text = tables.text(raw, mapping, "quantity")
        if not name:
            continue
        if SECTION.match(name) and not (code or unit_text or quantity_text):
            section = name  # «Поступление 03.07.2026» — заголовок, не товар
            continue
        if len(rows) >= MAX_ROWS:
            raise ChecklistError(f"Слишком много строк: больше {MAX_ROWS}.")
        try:
            quantity = tables.decimal(quantity_text)
        except ValueError:
            quantity = None
        index = mapping.get("expiry")
        row = Row(
            row=number,
            name=name,
            barcode=code,
            expiry=_expiry(raw[index]) if index is not None and index < len(raw) else None,
            unit_text=unit_text,
            qty_file=str(quantity.normalize()) if quantity is not None else None,
            section=section,
        )
        _match(row, known)
        rows.append(row)
    if not rows:
        raise ChecklistError("В файле не нашлось ни одной позиции.")
    return [asdict(row) for row in rows]


def summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"total": len(rows), "barcode": 0, "name": 0, "similar": 0, "manual": 0, "missing": 0}
    for row in rows:
        counts[row.get("match") or "missing"] = counts.get(row.get("match") or "missing", 0) + 1
    return counts


def load(document: StockDocument, content: bytes, filename: str) -> StockDocument:
    """Загрузить список в черновик инвентаризации (прежний список заменяется)."""
    if document.kind != StockDocument.Kind.INVENTORY or document.is_executed:
        raise ChecklistError("Список из файла загружается в черновик инвентаризации.")
    document.checklist = parse(content, filename)
    document.checklist_name = filename[:200]
    document.save(update_fields=["checklist", "checklist_name"])
    return document


@transaction.atomic
def save_barcodes(document: StockDocument) -> dict[str, Any]:
    """Записать штрихкоды из файла в прайс — подтверждённым строкам без штрихкода.

    Подтверждённая — совпала по названию, выбрана вручную или уже отмечена на полке.
    Штрихкод пишется в единицу упаковки (уп., фл., амп.), если у неё своего нет и
    он не занят другой позицией.
    """
    confirmed = set(
        document.lines.exclude(checklist_row=None).values_list("checklist_row", flat=True)
    )
    saved, skipped = 0, []
    rows = list(document.checklist or [])
    for row in rows:
        code, unit_id = row.get("barcode") or "", row.get("item_unit")
        if not code or not unit_id or row.get("match") == "barcode":
            continue
        if row.get("match") not in ("name", "manual") and row.get("row") not in confirmed:
            continue
        unit = ItemUnit.objects.select_related("item").filter(pk=unit_id).first()
        if unit is None:
            continue
        taken = catalog.find_by_barcode(code)
        if taken is not None and taken.item_id != unit.item_id:
            skipped.append(f"{code} («{row['name']}») уже у «{taken.item.name}»")
            continue
        if unit.barcode and unit.barcode != code:
            skipped.append(
                f"у «{unit.item.name}» ({unit.unit.name}) уже свой штрихкод {unit.barcode}"
            )
            continue
        if unit.barcode != code:
            unit.barcode = code
            unit.save(update_fields=["barcode"])
            saved += 1
        row["match"] = "barcode"
    document.checklist = rows
    document.save(update_fields=["checklist"])
    return {"saved": saved, "skipped": skipped}
