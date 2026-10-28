"""Жизненный цикл документа и журнал движений (ADR-004, ADR-005)."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db.models import Sum

from core import events, services
from core.context import acting_user
from core.models import DocumentError, LedgerError
from core.tests.testapp.models import SampleDocument, SampleLedger


def balance(account: str = "main") -> Decimal:
    total = SampleLedger.objects.filter(account=account).aggregate(total=Sum("amount"))["total"]
    return total or Decimal("0")


@pytest.fixture
def doc(db):
    return SampleDocument.objects.create(amount=Decimal("150.00"))


def test_new_document_is_draft(doc) -> None:
    assert doc.status == SampleDocument.Status.DRAFT
    assert not doc.is_executed


def test_execute_posts_entries_and_records_who(doc) -> None:
    user = get_user_model().objects.create_user(username="cashier", password="x")

    with acting_user(user):
        services.execute_document(doc)

    doc.refresh_from_db()
    assert doc.is_executed
    assert doc.executed_by == user
    assert doc.executed_at is not None
    assert balance() == Decimal("150.00")
    entry = services.entries_of(SampleLedger, doc).get()
    assert entry.document == doc
    assert entry.created_by == user


def test_document_cannot_be_executed_twice(doc) -> None:
    services.execute_document(doc)

    with pytest.raises(DocumentError, match="уже выполнен"):
        services.execute_document(doc)
    assert balance() == Decimal("150.00")


def test_stale_copy_cannot_execute_again(doc) -> None:
    stale = SampleDocument.objects.get(pk=doc.pk)
    services.execute_document(doc)

    with pytest.raises(DocumentError, match="уже выполнен"):
        services.execute_document(stale)


def test_failed_check_leaves_draft_without_entries(db) -> None:
    doc = SampleDocument.objects.create(amount=0)

    with pytest.raises(DocumentError, match="больше нуля"):
        services.execute_document(doc)

    doc.refresh_from_db()
    assert not doc.is_executed
    assert not SampleLedger.objects.exists()


def test_deleted_document_cannot_be_executed(doc) -> None:
    doc.delete()

    with pytest.raises(DocumentError, match="удалён"):
        services.execute_document(doc)


def test_executed_document_is_immutable(doc) -> None:
    services.execute_document(doc)
    doc.refresh_from_db()

    doc.comment = "исправление"
    with pytest.raises(DocumentError, match="нельзя изменить"):
        doc.save()
    with pytest.raises(DocumentError, match="нельзя удалить"):
        doc.delete()


def test_rollback_reverses_entries_and_returns_to_draft(doc) -> None:
    services.execute_document(doc)

    services.rollback_document(doc)

    doc.refresh_from_db()
    assert not doc.is_executed
    assert doc.executed_by is None
    assert balance() == Decimal("0")
    entries = services.entries_of(SampleLedger, doc)
    assert entries.count() == 2
    assert entries.filter(reversal_of__isnull=False).get().amount == Decimal("-150.00")


def test_draft_can_be_edited_after_rollback_and_executed_again(doc) -> None:
    services.execute_document(doc)
    services.rollback_document(doc)

    doc.amount = Decimal("200.00")
    doc.save()
    services.execute_document(doc)

    assert balance() == Decimal("200.00")
    assert services.entries_of(SampleLedger, doc).count() == 3


def test_rollback_of_draft_is_rejected(doc) -> None:
    with pytest.raises(DocumentError, match="только выполненный"):
        services.rollback_document(doc)


def test_forbidden_rollback_changes_nothing(db) -> None:
    doc = SampleDocument.objects.create(amount=100, forbid_rollback=True)
    services.execute_document(doc)

    with pytest.raises(DocumentError, match="Откат запрещён"):
        services.rollback_document(doc)

    doc.refresh_from_db()
    assert doc.is_executed
    assert balance() == Decimal("100")


def test_events_are_sent_inside_transaction(doc) -> None:
    received = []

    def listener(sender, document, **kwargs):
        received.append((sender, document.pk))

    events.document_executed.connect(listener, sender=SampleDocument)
    try:
        services.execute_document(doc)
    finally:
        events.document_executed.disconnect(listener, sender=SampleDocument)

    assert received == [(SampleDocument, doc.pk)]


def test_failing_listener_cancels_execution(doc) -> None:
    def failing(sender, document, **kwargs):
        raise DocumentError("Не хватает товара на складе.")

    events.document_executed.connect(failing, sender=SampleDocument)
    try:
        with pytest.raises(DocumentError, match="Не хватает товара"):
            services.execute_document(doc)
    finally:
        events.document_executed.disconnect(failing, sender=SampleDocument)

    doc.refresh_from_db()
    assert not doc.is_executed
    assert balance() == Decimal("0")


def test_ledger_entries_are_append_only(doc) -> None:
    services.execute_document(doc)
    entry = SampleLedger.objects.get()

    entry.amount = Decimal("1")
    with pytest.raises(LedgerError):
        entry.save()
    with pytest.raises(LedgerError):
        entry.delete()
    with pytest.raises(LedgerError):
        SampleLedger.objects.all().delete()


def test_document_history_is_recorded(doc) -> None:
    services.execute_document(doc)

    statuses = [h.status for h in doc.history.order_by("history_date")]

    assert statuses == ["draft", "executed"]
