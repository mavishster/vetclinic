"""Выгрузка таблиц в Excel — общая для всех отчётов (DRY)."""

import io
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Font

Column = tuple[str, str, int]  # ключ в строке, заголовок, ширина


def _cell(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return value


def table_xlsx(title: str, columns: list[Column], rows: Iterable[dict[str, Any]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title[:31]
    sheet.append([label for _, label, _ in columns])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append([_cell(row.get(key)) for key, _, _ in columns])
    for index, (_, _, width) in enumerate(columns, start=1):
        sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = width
        for cell in sheet[sheet.cell(row=1, column=index).column_letter][1:]:
            if isinstance(cell.value, date):
                cell.number_format = "DD.MM.YYYY"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def xlsx_response(
    filename: str, title: str, columns: list[Column], rows: Iterable[dict[str, Any]]
) -> HttpResponse:
    response = HttpResponse(
        table_xlsx(title, columns, rows),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
