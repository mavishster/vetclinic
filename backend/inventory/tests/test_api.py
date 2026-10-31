from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from inventory.models import Warehouse

URL = "/api/inventory/documents/"


@pytest.fixture
def api(db):
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    return client


@pytest.fixture
def drug(db):
    return catalog.save_item(
        Item(kind=Kind.GOODS, name="Витамины", group=ItemGroup.objects.get(name="Препараты"), base_unit=Unit.objects.get(name="таб.")),
        [{"unit": Unit.objects.get(name="таб."), "price": Decimal("3")},
         {"unit": Unit.objects.get(name="упак."), "ratio": Decimal("100"), "price": Decimal("250"), "barcode": "460111"}],
    )  # fmt: skip


def test_receipt_flow_lookup_balances_and_rollback(api, drug) -> None:
    warehouse = str(Warehouse.objects.get(name="Основной склад").pk)
    found = api.get("/api/inventory/stock/lookup/?barcode=460111").json()

    draft = api.post(
        URL,
        {"kind": "receipt", "warehouse": warehouse, "lines": [
            {"item_unit": found[0]["item_unit"], "quantity": "2", "price": "180", "series": "S-1", "expiry_date": "2027-05-01"}]},
        format="json",
    ).json()  # fmt: skip
    executed = api.post(f"{URL}{draft['id']}/execute/").json()
    balances = api.get("/api/inventory/stock/balances/?search=витамины").json()
    batches = api.get(f"/api/inventory/stock/batches/?item={drug.pk}").json()
    locked = api.patch(f"{URL}{draft['id']}/", {"comment": "x"}, format="json")
    rolled = api.post(f"{URL}{draft['id']}/rollback/").json()

    assert found[0]["unit_name"] == "упак." and found[0]["ratio"] == "100.000"
    assert draft["total"] == "360.00"
    assert executed["status"] == "executed"
    assert balances["rows"][0]["qty"] == "200.000"
    assert batches[0]["series"] == "S-1" and batches[0]["cost_per_base"] == "1.80"
    assert locked.status_code == 400
    assert rolled["status"] == "draft"


def test_write_off_error_is_readable(api, drug) -> None:
    warehouse = str(Warehouse.objects.get(name="Основной склад").pk)
    draft = api.post(
        URL, {"kind": "write_off", "warehouse": warehouse, "reason": "Бой",
              "lines": [{"item_unit": str(drug.units.get(unit__name="таб.").pk), "quantity": "5"}]}, format="json",
    ).json()  # fmt: skip

    response = api.post(f"{URL}{draft['id']}/execute/")

    assert response.status_code == 400
    assert "Не хватает «Витамины»" in response.json()["non_field_errors"][0]


def test_permissions(db) -> None:
    plain = APIClient()
    plain.force_authenticate(get_user_model().objects.create_user(username="u", password="x"))

    assert plain.get(URL).status_code == 403
    assert plain.get("/api/inventory/stock/balances/").status_code == 403


def test_inventory_fill_api_returns_expected(api, drug) -> None:
    warehouse = str(Warehouse.objects.get(name="Основной склад").pk)
    receipt = api.post(
        URL,
        {
            "kind": "receipt",
            "warehouse": warehouse,
            "lines": [
                {
                    "item_unit": str(drug.units.get(unit__name="таб.").pk),
                    "quantity": "30",
                    "price": "1",
                }
            ],
        },
        format="json",
    ).json()
    api.post(f"{URL}{receipt['id']}/execute/")
    draft = api.post(URL, {"kind": "inventory", "warehouse": warehouse}, format="json").json()

    filled = api.post(f"{URL}{draft['id']}/fill/", {}, format="json").json()

    assert filled["lines"][0]["qty_expected"] == "30.000"
    assert api.get("/api/inventory/stock/summary/").json() == {
        "expired": 0,
        "expiring": 0,
        "low": 0,
        "negative": 0,
    }


def test_item_with_stock_cannot_be_deleted(api, drug) -> None:
    warehouse = str(Warehouse.objects.get(name="Основной склад").pk)
    receipt = api.post(
        URL,
        {
            "kind": "receipt",
            "warehouse": warehouse,
            "lines": [
                {
                    "item_unit": str(drug.units.get(unit__name="таб.").pk),
                    "quantity": "5",
                    "price": "1",
                }
            ],
        },
        format="json",
    ).json()
    api.post(f"{URL}{receipt['id']}/execute/")

    response = api.delete(f"/api/catalog/items/{drug.pk}/")

    assert response.status_code == 400
    assert "уже используется" in response.json()["non_field_errors"][0]
