"""Отборы в списке товаров и услуг."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from catalog import services

D = Decimal


@pytest.fixture
def api() -> APIClient:
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    return client


@pytest.mark.django_db
def test_items_filter_by_prevention_kind(api: APIClient) -> None:
    """Фильтр по профилактике: своя отметка позиции или отметка её группы."""
    from catalog.models import Item, ItemGroup, Kind, PreventionKind, Unit

    unit = Unit.objects.get(name="мл")
    vaccines = ItemGroup.objects.create(
        name="Вакцины склада", kind=Kind.GOODS, prevention_kind=PreventionKind.VACCINATION
    )
    in_group = services.save_item(
        Item(kind=Kind.GOODS, name="Нобивак DHPPI", group=vaccines, base_unit=unit),
        [
            {
                "unit": unit.pk,
                "ratio": D("1"),
                "pricing": "fixed",
                "price": D("1500"),
                "for_sale": True,
            }
        ],
    )
    own = services.save_item(
        Item(
            kind=Kind.GOODS,
            name="Дронтал",
            group=ItemGroup.objects.filter(kind=Kind.GOODS).first(),
            base_unit=unit,
            prevention_kind=PreventionKind.DEWORMING,
        ),
        [
            {
                "unit": unit.pk,
                "ratio": D("1"),
                "pricing": "fixed",
                "price": D("300"),
                "for_sale": True,
            }
        ],
    )

    found = api.get("/api/catalog/items/?prevention_kind=vaccination").json()

    names = [row["name"] for row in (found["results"] if isinstance(found, dict) else found)]
    assert in_group.name in names and own.name not in names
