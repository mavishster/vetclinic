"""Общее для отчётов в API: период из запроса, деньги строкой, выгрузка в Excel."""

from datetime import date
from decimal import Decimal
from typing import Any

from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request


def period(request: Request) -> tuple[date, date]:
    """?from=ГГГГ-ММ-ДД&to=ГГГГ-ММ-ДД; по умолчанию — с начала месяца по сегодня."""
    today = timezone.localdate()
    try:
        date_from = date.fromisoformat(
            request.query_params.get("from") or today.replace(day=1).isoformat()
        )
        date_to = date.fromisoformat(request.query_params.get("to") or today.isoformat())
    except ValueError as error:
        raise ValidationError({"from": ["Даты в формате ГГГГ-ММ-ДД."]}) from error
    if date_to < date_from:
        raise ValidationError({"to": ["Конец периода раньше начала."]})
    return date_from, date_to


def wants_excel(request: Request) -> bool:
    return request.query_params.get("export") == "xlsx"


def as_text(rows: list[dict[str, Any]], hide: set[str] | None = None) -> list[dict[str, Any]]:
    """Числа — строкой (как во всём API); скрытые колонки (себестоимость) — None."""
    hidden = hide or set()
    return [
        {
            k: (None if k in hidden else str(v) if isinstance(v, Decimal) else v)
            for k, v in row.items()
        }
        for row in rows
    ]
