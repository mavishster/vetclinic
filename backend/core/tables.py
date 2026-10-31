"""Чтение таблиц из Excel и CSV — общее для всех импортов (прайс, остатки…).

Колонки узнаются по заголовкам с синонимами, без учёта регистра; строка заголовков
ищется в первых 15 строках (над ней может быть название документа).
"""

import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from openpyxl import load_workbook


class TableError(Exception):
    """Файл не удалось прочитать. Текст — для пользователя."""


def read_table(content: bytes, filename: str) -> list[list[Any]]:
    """Строки первого листа Excel (.xlsx) или CSV (UTF-8 / Windows-1251, ; , или Tab)."""
    if filename.lower().endswith(".csv"):
        for encoding in ("utf-8-sig", "cp1251"):
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise TableError("Не удалось прочитать CSV: неизвестная кодировка.")
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=";,\t")
        return [row for row in csv.reader(io.StringIO(text), dialect)]
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as error:  # noqa: BLE001 — любой битый файл = понятное сообщение
        raise TableError("Не удалось открыть файл. Нужен Excel (.xlsx) или CSV.") from error
    return [list(row) for row in workbook.worksheets[0].iter_rows(values_only=True)]


def header_map(row: list[Any], columns: dict[str, tuple[str, ...]]) -> dict[str, int]:
    """Какая колонка в какой ячейке строки заголовков."""
    mapping: dict[str, int] = {}
    for index, cell in enumerate(row):
        title = str(cell or "").strip().lower()
        for key, aliases in columns.items():
            if key not in mapping and title in aliases:
                mapping[key] = index
    return mapping


def find_header(
    table: list[list[Any]], columns: dict[str, tuple[str, ...]], required: str
) -> tuple[int, dict[str, int]]:
    """Строка заголовков — первая, где есть обязательная колонка."""
    for index, row in enumerate(table[:15]):
        mapping = header_map(row, columns)
        if required in mapping:
            return index, mapping
    title = columns[required][0].capitalize()
    raise TableError(f"Не найдена строка заголовков с колонкой «{title}».")


def text(row: list[Any], mapping: dict[str, int], key: str) -> str:
    """Значение ячейки текстом. Числа без дробной части — без «.0» (артикулы, штрихкоды)."""
    index = mapping.get(key)
    if index is None or index >= len(row) or row[index] is None:
        return ""
    value = row[index]
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, datetime):
        value = value.date()
    return str(value).strip()


def decimal(value: Any) -> Decimal | None:
    """Число из ячейки: «1 100,50», «1100.5 ₽». Пусто — None; не число — ValueError."""
    if value in (None, ""):
        return None
    cleaned = str(value).replace("\u00a0", "").replace(" ", "").replace("₽", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"не число: «{value}»") from None


def parse_date(value: str) -> date | None:
    """Дата из ячейки: 2027-06-30, 30.06.2027, 30.06.27 или 06.2027 (тогда — 1-е число месяца).
    Пусто — None; не дата — ValueError."""
    value = value.strip()
    if not value:
        return None
    for pattern in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    raise ValueError(f"не дата: «{value}»")
