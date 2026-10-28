"""Нумерация документов (ADR-012): префикс узла + порядковый номер по типу документа."""

from django.conf import settings
from django.db import IntegrityError, transaction

from core.models import DocumentCounter


def next_number(doc_type: str) -> str:
    """Следующий номер документа данного типа на этом узле: «K1-000123».

    Счётчик блокируется на время транзакции — два документа не получат один номер.
    """
    if not doc_type:
        raise ValueError("У документа не задан doc_type.")
    node = settings.NODE_ID
    with transaction.atomic():
        counter = (
            DocumentCounter.objects.select_for_update()
            .filter(doc_type=doc_type, node_id=node)
            .first()
        )
        if counter is None:
            try:
                with transaction.atomic():
                    counter = DocumentCounter.objects.create(doc_type=doc_type, node_id=node)
            except IntegrityError:  # счётчик только что создал параллельный запрос
                counter = DocumentCounter.objects.select_for_update().get(
                    doc_type=doc_type, node_id=node
                )
        counter.last_number += 1
        counter.save(update_fields=["last_number"])
    return f"{node}-{counter.last_number:06d}"
