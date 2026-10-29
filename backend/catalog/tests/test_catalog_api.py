import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from catalog.models import ItemGroup, Unit

URL = "/api/catalog/items/"


@pytest.fixture
def api(db):
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    return client


def ids():
    return {
        "pack": str(Unit.objects.get(name="упак.").pk),
        "tab": str(Unit.objects.get(name="таб.").pk),
        "service": str(Unit.objects.get(name="усл.").pk),
        "drugs": str(ItemGroup.objects.get(name="Препараты").pk),
        "feed": str(ItemGroup.objects.get(name="Корма").pk),
        "visits": str(ItemGroup.objects.get(name="Приём и консультации").pk),
    }


def test_create_goods_with_units_and_computed_price(api) -> None:
    i = ids()
    response = api.post(
        URL,
        {
            "kind": "goods", "name": "Корм Purina 85 г", "group": i["feed"], "base_unit": i["pack"],
            "manual_cost": "100",
            "units": [{"unit": i["pack"], "ratio": "1", "pricing": "markup"}],
        },
        format="json",
    )  # fmt: skip

    assert response.status_code == 201
    unit = response.json()["units"][0]
    assert unit["effective_markup"] == "25.00"
    assert unit["current_price"] == "125.00"


def test_validation_error_is_readable(api) -> None:
    i = ids()
    response = api.post(
        URL,
        {"kind": "goods", "name": "Без цены", "group": i["drugs"], "base_unit": i["tab"],
         "units": [{"unit": i["tab"], "ratio": "1", "pricing": "fixed"}]},
        format="json",
    )  # fmt: skip

    assert response.status_code == 400
    assert "укажите цену" in response.json()["non_field_errors"][0]


def test_list_filters_search_and_price_history(api) -> None:
    i = ids()
    service = api.post(
        URL,
        {"kind": "service", "name": "Первичный приём", "group": i["visits"], "base_unit": i["service"],
         "units": [{"unit": i["service"], "price": "900"}]},
        format="json",
    ).json()  # fmt: skip
    unit_id = service["units"][0]["id"]
    api.patch(
        f"{URL}{service['id']}/",
        {"units": [{"id": unit_id, "unit": i["service"], "price": "1000"}]},
        format="json",
    )

    services_only = api.get(f"{URL}?kind=service").json()["results"]
    found = api.get(f"{URL}?search=первичный").json()["results"]
    history = api.get(f"{URL}{service['id']}/price-history/").json()

    assert [s["name"] for s in services_only] == ["Первичный приём"]
    assert found[0]["units"][0]["price"] == "1000.00"
    assert [h["price"] for h in history] == ["1000.00", "900.00"]


def test_groups_filter_by_kind_and_permissions(api, db) -> None:
    goods_groups = api.get("/api/catalog/groups/?kind=goods").json()
    plain = APIClient()
    plain.force_authenticate(get_user_model().objects.create_user(username="u", password="x"))

    assert "Вакцины" in [g["name"] for g in goods_groups]
    assert "Хирургия" not in [g["name"] for g in goods_groups]
    assert plain.get(URL).status_code == 403
