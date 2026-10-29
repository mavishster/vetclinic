"""Импорт прайса из Excel или CSV: проверка (предпросмотр) и загрузка.

Колонки узнаются по заголовкам, без учёта регистра и с синонимами — так подходит
и наш шаблон, и выгрузки других программ (например, VetManager), если заголовки
похожи. Товар ищется по артикулу, а если его нет — по названию и виду: найденный
обновляется (цена, группа, артикул…), не найденный — создаётся.
"""

import csv
import io
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction
from openpyxl import Workbook, load_workbook

from catalog import services
from catalog.models import Item, ItemGroup, ItemUnit, Kind, Unit

MAX_ROWS = 5000

COLUMNS: dict[str, tuple[str, ...]] = {
    "name": ("название", "наименование", "номенклатура", "товар/услуга", "товар", "услуга"),
    "kind": ("вид", "тип"),
    "group": ("группа", "категория", "раздел"),
    "article": ("артикул", "код"),
    "unit": ("единица", "ед. изм.", "ед.изм.", "единица измерения", "ед", "ед."),
    "price": ("цена", "цена продажи", "розничная цена", "стоимость", "цена, руб."),
    "markup": ("наценка", "наценка, %", "наценка %"),
    "cost": ("себестоимость", "закупочная цена", "цена закупки", "закупка"),
    "barcode": ("штрихкод", "штрих-код", "ean", "barcode"),
}
SERVICE_WORDS = {"услуга", "услуги", "service"}


class ImportError_(Exception):
    """Файл не удалось прочитать. Текст — для пользователя."""


@dataclass
class RowResult:
    line: int
    name: str
    kind: str = Kind.GOODS
    group: str = ""
    unit: str = ""
    price: str | None = None
    action: str = "create"  # create | update | unchanged | error
    error: str = ""
    _data: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class ImportResult:
    rows: list[RowResult]
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: int = 0

    def as_dict(self, limit: int = 500) -> dict[str, Any]:
        rows = [{k: v for k, v in asdict(r).items() if k != "_data"} for r in self.rows[:limit]]
        return {
            "rows": rows,
            "total": len(self.rows),
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "errors": self.errors,
        }


# --- Чтение файла ------------------------------------------------------------------


def _read_table(content: bytes, filename: str) -> list[list[Any]]:
    if filename.lower().endswith(".csv"):
        for encoding in ("utf-8-sig", "cp1251"):
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ImportError_("Не удалось прочитать CSV: неизвестная кодировка.")
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=";,\t")
        return [row for row in csv.reader(io.StringIO(text), dialect)]
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as error:  # noqa: BLE001 — любой битый файл = понятное сообщение
        raise ImportError_("Не удалось открыть файл. Нужен Excel (.xlsx) или CSV.") from error
    sheet = workbook.worksheets[0]
    return [list(row) for row in sheet.iter_rows(values_only=True)]


def _header_map(row: list[Any]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, cell in enumerate(row):
        title = str(cell or "").strip().lower()
        for key, aliases in COLUMNS.items():
            if key not in mapping and title in aliases:
                mapping[key] = index
    return mapping


def _find_header(table: list[list[Any]]) -> tuple[int, dict[str, int]]:
    for index, row in enumerate(table[:15]):
        mapping = _header_map(row)
        if "name" in mapping:
            return index, mapping
    raise ImportError_("Не найдена строка заголовков с колонкой «Название».")


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    text = str(value).replace("\u00a0", "").replace(" ", "").replace("₽", "").replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        raise ValueError(f"не число: «{value}»") from None


def _text(row: list[Any], mapping: dict[str, int], key: str) -> str:
    index = mapping.get(key)
    if index is None or index >= len(row) or row[index] is None:
        return ""
    value = row[index]
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # артикулы и штрихкоды Excel хранит как числа
    return str(value).strip()


# --- Разбор строк ------------------------------------------------------------------


def _parse(content: bytes, filename: str) -> list[RowResult]:
    table = _read_table(content, filename)
    header_index, mapping = _find_header(table)
    rows: list[RowResult] = []
    for offset, raw in enumerate(table[header_index + 1 :], start=header_index + 2):
        name = _text(raw, mapping, "name")
        if not name:
            continue
        if len(rows) >= MAX_ROWS:
            raise ImportError_(f"Слишком много строк: больше {MAX_ROWS}. Разбейте файл на части.")
        kind = Kind.SERVICE if _text(raw, mapping, "kind").lower() in SERVICE_WORDS else Kind.GOODS
        result = RowResult(line=offset, name=name, kind=kind)
        try:
            data = {
                "group": _text(raw, mapping, "group"),
                "article": _text(raw, mapping, "article"),
                "unit": _text(raw, mapping, "unit") or ("усл." if kind == Kind.SERVICE else "шт."),
                "price": _decimal(_text(raw, mapping, "price")),
                "markup": _decimal(_text(raw, mapping, "markup")),
                "cost": _decimal(_text(raw, mapping, "cost")),
                "barcode": _text(raw, mapping, "barcode"),
            }
        except ValueError as error:
            result.action, result.error = "error", f"Строка {offset}: {error}"
            rows.append(result)
            continue
        result.group, result.unit, result._data = data["group"], data["unit"], data
        result.price = str(data["price"]) if data["price"] is not None else None
        if not data["group"]:
            result.action, result.error = "error", "Не указана группа."
        elif data["price"] is None and data["markup"] is None:
            result.action, result.error = "error", "Не указана цена (или наценка)."
        elif data["price"] is not None and data["price"] < 0:
            result.action, result.error = "error", "Цена не может быть отрицательной."
        rows.append(result)
    return rows


def _find_item(row: RowResult) -> Item | None:
    items = Item.objects.filter(kind=row.kind)
    if row._data["article"]:
        found = items.filter(article__iexact=row._data["article"]).first()
        if found:
            return found
    return items.filter(name__iexact=row.name).first()


def _unit_changed(unit: ItemUnit | None, data: dict[str, Any]) -> bool:
    if unit is None:
        return True
    if data["price"] is not None:
        return unit.pricing != ItemUnit.Pricing.FIXED or unit.price != data["price"]
    return unit.pricing != ItemUnit.Pricing.MARKUP or unit.markup_percent != data["markup"]


def _classify(row: RowResult) -> None:
    if row.action == "error":
        return
    item = _find_item(row)
    if item is None:
        row.action = "create"
        return
    data = row._data
    unit = item.units.filter(unit__name__iexact=row.unit).first()
    changed = (
        _unit_changed(unit, data)
        or item.group.name.lower() != data["group"].lower()
        or (data["article"] and item.article != data["article"])
        or (data["barcode"] and item.barcode != data["barcode"])
        or (data["cost"] is not None and item.manual_cost != data["cost"])
    )
    row.action = "update" if changed else "unchanged"


# --- Применение --------------------------------------------------------------------


def _apply(row: RowResult) -> None:
    data = row._data
    group = ItemGroup.objects.filter(name__iexact=data["group"], kind=row.kind).first()
    if group is None:
        group = ItemGroup.objects.create(name=data["group"], kind=row.kind)
    unit = Unit.objects.filter(name__iexact=row.unit).first() or Unit.objects.create(name=row.unit)
    item = _find_item(row) or Item(kind=row.kind, name=row.name, base_unit=unit)
    item.group = group
    item.article = data["article"] or item.article
    item.barcode = data["barcode"] or item.barcode
    if data["cost"] is not None:
        item.manual_cost = data["cost"]
    current = {str(u.unit_id): u for u in item.units.all()} if item.pk else {}
    units: list[services.UnitData] = [
        {"id": u.pk, "unit": u.unit_id, "ratio": u.ratio, "pricing": u.pricing, "price": u.price,
         "markup_percent": u.markup_percent, "for_sale": u.for_sale}
        for u in current.values()
    ]  # fmt: skip
    pricing = (
        {"pricing": ItemUnit.Pricing.FIXED, "price": data["price"]}
        if data["price"] is not None
        else {"pricing": ItemUnit.Pricing.MARKUP, "price": None, "markup_percent": data["markup"]}
    )
    existing = next((u for u in units if str(u["unit"]) == str(unit.pk)), None)
    if existing is not None:
        existing.update(pricing)  # type: ignore[typeddict-item]
    else:
        units.append({"unit": unit.pk, "ratio": Decimal("1"), "for_sale": True, **pricing})  # type: ignore[typeddict-item]
    services.save_item(item, units)


def preview(content: bytes, filename: str) -> ImportResult:
    """Проверить файл, ничего не меняя: что будет создано, обновлено, какие ошибки."""
    rows = _parse(content, filename)
    for row in rows:
        _classify(row)
    return _summary(rows)


def commit(content: bytes, filename: str) -> ImportResult:
    """Загрузить прайс. Строки с ошибками пропускаются, остальные — одной транзакцией."""
    rows = _parse(content, filename)
    with transaction.atomic():
        for row in rows:
            _classify(row)
            if row.action in {"create", "update"}:
                try:
                    with transaction.atomic():
                        _apply(row)
                except services.CatalogError as error:
                    row.action, row.error = "error", str(error)
    return _summary(rows)


def _summary(rows: list[RowResult]) -> ImportResult:
    result = ImportResult(rows=rows)
    for row in rows:
        match row.action:
            case "create":
                result.created += 1
            case "update":
                result.updated += 1
            case "unchanged":
                result.unchanged += 1
            case _:
                result.errors += 1
    return result


def template() -> bytes:
    """Шаблон для заполнения прайса."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Прайс"
    sheet.append(["Название", "Вид", "Группа", "Единица", "Цена", "Наценка, %", "Себестоимость",
                  "Артикул", "Штрихкод"])  # fmt: skip
    sheet.append(["Первичный приём", "Услуга", "Приём и консультации", "усл.", 900, None, None,
                  "", ""])  # fmt: skip
    sheet.append(["Нобивак DHPPi (доза)", "Товар", "Вакцины", "доза", 1100, None, 650,
                  "NB-DHPPI", ""])  # fmt: skip
    sheet.append(["Корм Purina 85 г", "Товар", "Корма", "шт.", None, 25, 100, "", "7613035347717"])
    for column, width in zip("ABCDEFGHI", (40, 10, 28, 10, 10, 12, 14, 14, 16), strict=True):
        sheet.column_dimensions[column].width = width
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
