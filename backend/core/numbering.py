"""Нумерация документов (ADR-012): префикс узла + порядковый номер по типу документа."""

from django.conf import settings
from django.db import IntegrityError, transaction

from core.models import DocumentCounter


def next_value(counter_name: str) -> int:
    """Следующее значение счётчика на этом узле (1, 2, 3…).

    Счётчик блокируется на время транзакции — два документа не получат одно значение.
    """
    if not counter_name:
        raise ValueError("Не задано имя счётчика.")
    node = settings.NODE_ID
    with transaction.atomic():
        counter = (
            DocumentCounter.objects.select_for_update()
            .filter(doc_type=counter_name, node_id=node)
            .first()
        )
        if counter is None:
            try:
                with transaction.atomic():
                    counter = DocumentCounter.objects.create(doc_type=counter_name, node_id=node)
            except IntegrityError:  # счётчик только что создал параллельный запрос
                counter = DocumentCounter.objects.select_for_update().get(
                    doc_type=counter_name, node_id=node
                )
        counter.last_number += 1
        counter.save(update_fields=["last_number"])
    return int(counter.last_number)


def reserve(counter_name: str, value: int) -> None:
    """Поднять счётчик не ниже value: номера, занятые вручную или при переносе,
    больше не выдаются заново."""
    next_value(counter_name)  # счётчик гарантированно существует
    with transaction.atomic():
        counter = DocumentCounter.objects.select_for_update().get(
            doc_type=counter_name, node_id=settings.NODE_ID
        )
        if counter.last_number < value:
            counter.last_number = value
            counter.save(update_fields=["last_number"])


def next_number(doc_type: str) -> str:
    """Следующий номер документа данного типа на этом узле: «K1-000123»."""
    if not doc_type:
        raise ValueError("У документа не задан doc_type.")
    return f"{settings.NODE_ID}-{next_value(doc_type):06d}"
