"""Типы полей для денег и количеств (ADR-011). Используются всеми модулями.

float для денег и количеств запрещён: только Decimal с фиксированной точностью.
"""

from typing import Any

from django.db import models


class MoneyField(models.DecimalField):  # type: ignore[type-arg]
    """Деньги: до 9 999 999 999,99 с точностью до копейки."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("max_digits", 12)
        kwargs.setdefault("decimal_places", 2)
        super().__init__(*args, **kwargs)


class QuantityField(models.DecimalField):  # type: ignore[type-arg]
    """Количество: до 99 999 999 999,999 — с запасом для мл и таблеток."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("max_digits", 14)
        kwargs.setdefault("decimal_places", 3)
        super().__init__(*args, **kwargs)
