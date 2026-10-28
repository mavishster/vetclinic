import pytest

from core import services
from core.tests.testapp.models import OtherDocument, SampleDocument


@pytest.mark.django_db
def test_numbers_are_sequential_with_node_prefix(settings) -> None:
    settings.NODE_ID = "K1"

    assert services.next_number("invoice") == "K1-000001"
    assert services.next_number("invoice") == "K1-000002"


@pytest.mark.django_db
def test_each_document_type_has_own_counter() -> None:
    services.next_number("invoice")

    assert services.next_number("receipt").endswith("-000001")


@pytest.mark.django_db
def test_each_node_has_own_counter(settings) -> None:
    settings.NODE_ID = "K1"
    services.next_number("invoice")
    settings.NODE_ID = "CLOUD"

    assert services.next_number("invoice") == "CLOUD-000001"


def test_doc_type_is_required() -> None:
    with pytest.raises(ValueError):
        services.next_number("")


@pytest.mark.django_db
def test_document_gets_number_on_creation() -> None:
    first = SampleDocument.objects.create(amount=10)
    second = SampleDocument.objects.create(amount=10)
    other = OtherDocument.objects.create()

    assert first.number.endswith("-000001")
    assert second.number.endswith("-000002")
    assert other.number.endswith("-000001")
