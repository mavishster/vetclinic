"""Импорт остатков из Excel / CSV (например, выгрузки VetManager) — черновиком прихода.

Товар ищется по штрихкоду (единицы или товара), затем по артикулу, затем по названию.
Найденные строки становятся черновиком прихода «Ввод остатков»: его можно проверить,
поправить и выполнить. Ненайденные товары показываются списком — их сначала заводят
в каталог (например, импортом прайса), а потом загружают остатки повторно.
"""

import io
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from openpyxl import Workbook

from catalog import services as catalog
from catalog.models import Item, Kind
from core import tables
from inventory import services
from inventory.models import StockDocument

MAX_ROWS = 5000

COLUMNS: dict[str, tuple[str, ...]] = {
    "name": ("название", "наименование", "номенклатура", "товар"),
    "article": ("артикул", "код"),
    "barcode": ("штрихкод", "штрих-код", "ean", "barcode"),
    "unit": ("единица", "ед. изм.", "ед.изм.", "единица измерения", "ед", "ед."),
    "quantity": ("количество", "остаток", "кол-во", "кол."),
    "price": ("закупочная цена", "цена закупки", "себестоимость", "цена", "цена за единицу"),
    "series": ("серия", "партия", "серия / партия"),
    "expiry": ("срок годности", "годен до", "срок"),
}


class ImportError_(Exception):
    """Файл не удалось прочитать. Текст — для пользователя."""


@dataclass
class Row:
    line: int
    name: str
    unit: str = ""
    quantity: str | None = None
    price: str | None = None
    series: str = ""
    expiry: Any = None
    item_name: str = ""  # что нашлось в каталоге
    error: str = ""
    _unit_obj: Any = field(default=None, repr=False)


def _find_unit(name: str, article: str, code: str, unit_name: str) -> tuple[Any, str]:
    """Единица товара по штрихкоду / артикулу / названию. Возвращает (единица, ошибка)."""
    unit = catalog.find_by_barcode(code) if code else None
    if unit is not None and unit.item.kind == Kind.GOODS:
        if unit_name and unit.unit.name.lower() != unit_name.lower():
            other = (
                unit.item.units.select_related("unit", "item")
                .filter(unit__name__iexact=unit_name)
                .first()
            )
            return (other, "") if other else (None, f"У товара нет единицы «{unit_name}».")
        return unit, ""
    goods = Item.objects.filter(kind=Kind.GOODS)
    item = goods.filter(article__iexact=article).first() if article else None
    item = item or (goods.filter(name__iexact=name).first() if name else None)
    if item is None:
        return None, "Товар не найден в каталоге."
    units = item.units.select_related("unit", "item")
    if unit_name:
        found = units.filter(unit__name__iexact=unit_name).first()
        return (found, "") if found else (None, f"У товара нет единицы «{unit_name}».")
    return catalog.base_item_unit(item), ""


def _parse(content: bytes, filename: str) -> list[Row]:
    try:
        table = tables.read_table(content, filename)
        header, mapping = tables.find_header(table, COLUMNS, "quantity")
    except tables.TableError as error:
        raise ImportError_(str(error)) from error
    if not {"name", "article", "barcode"} & mapping.keys():
        raise ImportError_("Нужна хотя бы одна из колонок: «Название», «Артикул», «Штрихкод».")
    rows: list[Row] = []
    for offset, raw in enumerate(table[header + 1 :], start=header + 2):
        name, article, code = (tables.text(raw, mapping, k) for k in ("name", "article", "barcode"))
        if not (name or article or code):
            continue
        if len(rows) >= MAX_ROWS:
            raise ImportError_(f"Слишком много строк: больше {MAX_ROWS}. Разбейте файл на части.")
        row = Row(
            line=offset,
            name=name or article or code,
            unit=tables.text(raw, mapping, "unit"),
            series=tables.text(raw, mapping, "series"),
        )
        try:
            quantity = tables.decimal(tables.text(raw, mapping, "quantity"))
            price = tables.decimal(tables.text(raw, mapping, "price"))
            row.expiry = tables.parse_date(tables.text(raw, mapping, "expiry"))
        except ValueError as error:
            row.error = f"Строка {offset}: {error}"
            rows.append(row)
            continue
        row.quantity = str(quantity) if quantity is not None else None
        row.price = str(price) if price is not None else None
        if quantity is None or quantity <= 0:
            row.error = "Количество должно быть больше нуля."
        elif price is None or price < 0:
            row.error = "Укажите закупочную цену (не отрицательную)."
        else:
            unit, error = _find_unit(name, article, code, row.unit)
            row.error, row._unit_obj = error, unit
            if unit is not None:
                row.item_name, row.unit = unit.item.name, unit.unit.name
        rows.append(row)
    return rows


def _summary(rows: list[Row]) -> dict[str, Any]:
    good = [r for r in rows if not r.error]
    return {
        "rows": [{k: v for k, v in asdict(r).items() if k != "_unit_obj"} for r in rows[:500]],
        "total": len(rows),
        "ready": len(good),
        "errors": len(rows) - len(good),
        "sum": str(
            sum(
                (Decimal(r.price or 0) * Decimal(r.quantity or 0) for r in good), Decimal("0")
            ).quantize(Decimal("0.01"))
        ),
    }


def preview(content: bytes, filename: str) -> dict[str, Any]:
    """Проверить файл, ничего не меняя."""
    return _summary(_parse(content, filename))


def commit(content: bytes, filename: str, warehouse: Any) -> dict[str, Any]:
    """Создать черновик прихода «Ввод остатков» из строк без ошибок."""
    rows = _parse(content, filename)
    good = [r for r in rows if not r.error]
    if not good:
        raise ImportError_("В файле нет ни одной строки без ошибок — приход не создан.")
    document = services.save_document(
        StockDocument(
            kind=StockDocument.Kind.RECEIPT,
            warehouse_id=getattr(warehouse, "pk", warehouse),
            comment=f"Ввод остатков из файла «{filename}»",
        ),
        [
            {
                "item_unit": r._unit_obj,
                "quantity": Decimal(r.quantity or 0),
                "price": Decimal(r.price or 0),
                "series": r.series,
                "expiry_date": r.expiry,
            }
            for r in good
        ],
    )
    return {**_summary(rows), "document": str(document.pk)}


def template() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Остатки"
    sheet.append(
        [
            "Название",
            "Артикул",
            "Штрихкод",
            "Единица",
            "Количество",
            "Закупочная цена",
            "Серия",
            "Срок годности",
        ]
    )
    sheet.append(["Нобивак Rabies", "NB-RAB", "", "доза", 10, 450, "A123", "31.12.2027"])
    sheet.append(
        [
            "Фелиферон раствор для инъекций 5 флаконов.",
            "",
            "4680015640031",
            "упак.",
            2,
            2000,
            "F-77",
            "06.2027",
        ]
    )
    for column, width in zip("ABCDEFGH", (42, 12, 16, 10, 12, 16, 12, 14), strict=True):
        sheet.column_dimensions[column].width = width
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
