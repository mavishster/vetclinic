"""Удаление позиции прайса: только неиспользованной; иначе — список мест (проверяется на счетах)."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from billing import services as billing
from billing.models import Invoice
from catalog import services
from catalog.models import Item, ItemGroup, Kind, Unit
from clients import services as clients
from clients.models import Client

D = Decimal


@pytest.fixture
def api(db):
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    return client


def service(name="Осмотр"):
    return services.save_item(
        Item(
            kind=Kind.SERVICE,
            name=name,
            group=ItemGroup.objects.get(name="Приём и консультации"),
            base_unit=Unit.objects.get(name="усл."),
        ),
        [{"unit": Unit.objects.get(name="усл."), "price": D("500")}],
    )


def test_unused_item_is_deleted(api) -> None:
    item = service()

    usage = api.get(f"/api/catalog/items/{item.pk}/usage/").json()
    deleted = api.delete(f"/api/catalog/items/{item.pk}/")

    assert usage == {"total": 0, "places": []}
    assert deleted.status_code == 204
    assert not Item.objects.filter(pk=item.pk).exists()


def test_item_in_invoice_cannot_be_deleted(api) -> None:
    item = service()
    owner = clients.save_client(Client(last_name="Петров"))
    billing.save_invoice(
        Invoice(client=owner), [{"item_unit": item.units.get(), "quantity": D("1")}]
    )

    usage = api.get(f"/api/catalog/items/{item.pk}/usage/").json()
    refused = api.delete(f"/api/catalog/items/{item.pk}/")

    assert usage["places"] == [{"title": "строки счетов", "count": 1}]
    assert refused.status_code == 400
    assert "строки счетов — 1" in refused.json()["non_field_errors"][0]


def test_item_in_combination_is_used_but_combination_itself_can_be_deleted(api) -> None:
    part = service("Приём в составе")
    combo = services.save_combination(Item(name="Комплекс", group=ItemGroup.objects.get(name="Приём и консультации")),
                                      [{"item_unit": part.units.get()}])  # fmt: skip

    assert api.get(f"/api/catalog/items/{part.pk}/usage/").json()["places"] == [
        {"title": "позиции комбинации", "count": 1}
    ]
    assert (
        api.delete(f"/api/catalog/items/{combo.pk}/").status_code == 204
    )  # строки самой комбинации — её части
    assert api.delete(f"/api/catalog/items/{part.pk}/").status_code == 204  # теперь свободна
