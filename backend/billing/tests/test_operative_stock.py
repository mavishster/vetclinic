"""Оперативный склад: счёт — только со склада продажи, перемещение по сканеру,
«нужно переместить», доступ к складам по ролям, разбор DataMatrix."""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from billing import services as billing
from billing.models import Invoice
from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from clients import services as clients
from clients.models import Client
from core import services as core
from inventory import services as inventory
from inventory.models import StockDocument, Warehouse

D = Decimal


@pytest.fixture
def main(db):
    return Warehouse.objects.get(name="Основной склад")


@pytest.fixture
def operative(db):
    return Warehouse.objects.get(name="Оперативный склад")


@pytest.fixture
def drug(main):
    item = catalog.save_item(
        Item(kind=Kind.GOODS, name="Фелиферон", group=ItemGroup.objects.get(name="Препараты"), base_unit=Unit.objects.get(name="фл.")),
        [{"unit": Unit.objects.get(name="фл."), "price": D("700")},
         {"unit": Unit.objects.get(name="упак."), "ratio": D("5"), "price": D("3500"), "for_purchase": True, "barcode": "4680015640031"}],
    )  # fmt: skip
    pack = item.units.get(unit__name="упак.")
    for series, expiry in (("LATE", date(2028, 1, 1)), ("EARLY", date(2027, 3, 1))):
        doc = inventory.save_document(StockDocument(kind="receipt", warehouse=main),
                                      [{"item_unit": pack, "quantity": D("2"), "price": D("2000"), "series": series, "expiry_date": expiry}])  # fmt: skip
        core.execute_document(doc)
    return item


def test_main_is_storage_and_invoice_sells_from_operative(main, operative, drug) -> None:
    owner = clients.save_client(Client(last_name="Петров"))

    invoice = billing.save_invoice(
        Invoice(client=owner), [{"item_unit": drug.units.get(unit__name="фл.")}]
    )

    assert main.kind == "storage" and operative.kind == "sale"
    assert invoice.warehouse == operative
    with pytest.raises(billing.InvoiceError, match="только со склада продажи"):
        billing.save_invoice(
            Invoice(client=owner, warehouse=main), [{"item_unit": drug.units.get(unit__name="фл.")}]
        )


def test_scan_recommends_earliest_expiry_and_transfer(main, operative, drug) -> None:
    found = inventory.scan_for_transfer("4680015640031", main, operative)

    assert found["unit"] == "упак." and [b["series"] for b in found["batches"]] == ["EARLY", "LATE"]
    assert found["recommended"] == found["batches"][0]["batch"]
    assert found["batches"][0]["qty_unit"] == D("2.000")

    doc = inventory.quick_transfer(
        main,
        operative,
        [
            {
                "item_unit": drug.units.get(unit__name="упак."),
                "quantity": D("1"),
                "batch": found["recommended"],
            }
        ],
    )

    assert doc.status == "executed"
    assert inventory.available(drug, operative) == D("5")
    assert inventory.available(drug, main) == D("15")


def test_negative_on_operative_shows_in_replenish(main, operative, drug) -> None:
    owner = clients.save_client(Client(last_name="Петров"))
    invoice = billing.save_invoice(
        Invoice(client=owner), [{"item_unit": drug.units.get(unit__name="фл."), "quantity": D("3")}]
    )
    core.execute_document(invoice)  # на оперативном пусто — минус (продажа в минус разрешена)

    rows = inventory.to_replenish()

    assert [(r["item_name"], r["qty"], r["need"], r["available"]) for r in rows] == [
        ("Фелиферон", D("-3"), D("3"), D("20"))
    ]
    assert inventory.summary()["replenish"] == 1


def test_gs1_datamatrix_parsing(main, operative, drug) -> None:
    code = "0104680015640031" + "17270301" + "10EARLY\x1d" + "21ABC123"
    parsed = inventory.parse_gs1(code)

    assert parsed == {
        "gtin": "04680015640031",
        "ean": "4680015640031",
        "batch": "EARLY",
        "expiry": date(2027, 3, 1),
    }
    assert inventory.parse_gs1("(01)04680015640031(17)280101(10)LATE")["batch"] == "LATE"
    assert inventory.parse_gs1("4680015640031") is None
    found = inventory.scan_for_transfer(code, main, operative)
    assert found["scanned_series"] == "EARLY" and found["scanned_batch"] == found["recommended"]


def test_warehouse_access_by_roles(main, operative, drug) -> None:
    operators = Group.objects.create(name="Операторы")
    core.set_entity_permissions(operators, "inventory.stockmovement", {"view"})
    core.set_entity_permissions(operators, "inventory.warehouse", {"view"})
    main.access_roles.add(Group.objects.create(name="Склад"))  # основной — только роли «Склад»
    user = get_user_model().objects.create_user(username="op", password="x")
    user.groups.add(operators)
    api = APIClient()
    api.force_authenticate(user)

    warehouses = [w["name"] for w in api.get("/api/inventory/warehouses/").json()]
    balances = {
        r["warehouse_name"] for r in api.get("/api/inventory/stock/balances/").json()["rows"]
    }

    assert "Основной склад" not in warehouses and "Оперативный склад" in warehouses
    assert "Основной склад" not in balances


def test_transfer_api(main, operative, drug) -> None:
    api = APIClient()
    api.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))

    scan = api.get(
        f"/api/inventory/transfer/?code=4680015640031&from={main.pk}&to={operative.pk}"
    ).json()
    done = api.post("/api/inventory/transfer/", {"from": str(main.pk), "to": str(operative.pk),
                    "lines": [{"item_unit": scan["item_unit"], "quantity": "2", "batch": scan["recommended"]}]}, format="json")  # fmt: skip
    unknown = api.get(f"/api/inventory/transfer/?code=000&from={main.pk}&to={operative.pk}")

    assert scan["batches"][0]["series"] == "EARLY"
    assert done.status_code == 201 and inventory.available(drug, operative) == D("10")
    assert unknown.status_code == 400


def test_lookup_shows_operative_stock_not_main(main, operative, drug) -> None:
    found = billing.lookup("фелиферон")
    pack = next(r for r in found if r["unit"] == "упак.")
    assert pack["stock"] in ("0", "0.000", "0E-3") or D(pack["stock"]) == 0  # всё лежит на основном

    inventory.quick_transfer(
        main, operative, [{"item_unit": drug.units.get(unit__name="упак."), "quantity": D("1")}]
    )

    pack = next(r for r in billing.lookup("фелиферон") if r["unit"] == "упак.")
    assert D(pack["stock"]) == D("1")


def test_rolled_back_documents_vanish_from_turnover(main, operative, drug) -> None:
    from django.utils import timezone

    doc = inventory.quick_transfer(
        main, operative, [{"item_unit": drug.units.get(unit__name="упак."), "quantity": D("1")}]
    )
    core.rollback_document(doc)
    today = timezone.localdate()

    rows = {r["name"]: r for r in inventory.turnover(today, today, operative)}

    assert "Фелиферон" not in rows  # перемещение откатили — в обороте его нет
