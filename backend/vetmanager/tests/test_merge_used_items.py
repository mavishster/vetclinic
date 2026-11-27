"""Объединение уже использованных позиций (ADR-026). Тест на верхнем уровне: задевает
счета, склад и связи с VetManager.

После переноса из VetManager «Пинпрамиль …, 1табл.» и «Пинпрамиль …, 4табл.» — две
позиции, и по обеим есть счета. Должна остаться одна: учёт в таблетках, упаковка = 4 таб.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from billing import services as billing
from billing.models import Invoice, InvoiceLine
from catalog import services as catalog
from catalog.models import Item, ItemGroup, ItemUnit, Kind, Unit
from clients import services as clients
from clients.models import Client
from core import services as core
from inventory import services as inventory
from inventory.models import MinStock, StockDocument, Warehouse
from vetmanager.models import Imported

D = Decimal


def goods(name, unit, price, barcode=""):
    return catalog.save_item(
        Item(
            kind=Kind.GOODS,
            name=name,
            group=ItemGroup.objects.get(name="Препараты"),
            base_unit=Unit.objects.get(name=unit),
        ),
        [{"unit": Unit.objects.get(name=unit), "price": D(price), "barcode": barcode}],
    )


@pytest.fixture
def pair(db):
    tablet = goods("Пинпрамиль 4мг/10мг, для для кошек и котят, 1табл.", "таб.", "110")
    pack = goods(
        "Пинпрамиль 4мг/10мг, для кошек и котят(от 0,5 до 2 кг), 4табл.",
        "упак.",
        "425",
        barcode="4600000000017",
    )
    return tablet, pack


@pytest.fixture
def invoices(pair):
    tablet, pack = pair
    client = clients.save_client(Client(last_name="Петров"))
    invoice = billing.save_invoice(
        Invoice(client=client),
        [
            {"item_unit": tablet.units.get(), "quantity": D("2")},
            {"item_unit": pack.units.get(), "quantity": D("1")},
        ],
    )
    return core.execute_document(invoice)


def plan(tablet, pack):
    tab, upak = Unit.objects.get(name="таб."), Unit.objects.get(name="упак.")
    return {
        "main_id": pack.pk,
        "item_ids": [pack.pk, tablet.pk],
        "name": "Пинпрамиль 4мг/10мг для кошек и котят (0,5–2 кг)",
        "base_unit_id": tab.pk,
        "units": [
            {"item_unit": pack.units.get().pk, "unit": upak.pk, "ratio": D("4")},
            {"item_unit": tablet.units.get().pk, "unit": tab.pk, "ratio": D("1")},
        ],
    }


def test_preview_changes_nothing(pair, invoices) -> None:
    tablet, pack = pair

    preview = catalog.merge_items(**plan(tablet, pack), dry_run=True)

    assert {"title": "строки счетов", "count": 2} in preview["changes"]
    assert preview["units"] == [{"unit": "таб.", "ratio": "1"}, {"unit": "упак.", "ratio": "4"}]
    assert Item.objects.filter(pk=tablet.pk).exists()
    assert InvoiceLine.objects.filter(item=tablet).count() == 1


def test_merge_used_items(pair, invoices) -> None:
    tablet, pack = pair
    Imported.objects.create(kind="item", external_id="77", target_id=tablet.pk)
    total_before = Invoice.objects.get(pk=invoices.pk).total

    catalog.merge_items(**plan(tablet, pack), dry_run=False)

    main = Item.objects.get(pk=pack.pk)
    assert main.name == "Пинпрамиль 4мг/10мг для кошек и котят (0,5–2 кг)"
    assert main.base_unit.name == "таб."
    assert sorted((u.unit.name, u.ratio, u.price) for u in main.units.all()) == [
        ("таб.", D("1"), D("110")),
        ("упак.", D("4"), D("425")),
    ]
    assert not Item.objects.filter(pk=tablet.pk).exists()  # дубль удалён
    lines = {line.item_unit.unit.name: line for line in InvoiceLine.objects.filter(item=main)}
    assert (lines["таб."].quantity, lines["таб."].qty_base) == (D("2"), D("2"))
    assert (lines["упак."].quantity, lines["упак."].qty_base) == (D("1"), D("4"))  # 1 упак = 4 таб
    assert Invoice.objects.get(pk=invoices.pk).total == total_before  # суммы не меняются
    assert Imported.objects.get(external_id="77").target_id == main.pk
    assert catalog.find_by_barcode("4600000000017").item == main


def test_draft_inventory_and_min_stock_are_converted(pair) -> None:
    tablet, pack = pair
    main_store = Warehouse.objects.get(name="Основной склад")
    MinStock.objects.create(item=pack, warehouse=main_store, min_qty=D("2"))  # 2 упак.
    MinStock.objects.create(item=tablet, warehouse=main_store, min_qty=D("3"))  # 3 таб.
    draft = inventory.save_document(
        StockDocument(kind=StockDocument.Kind.INVENTORY, warehouse=main_store),
        [{"item_unit": pack.units.get(), "quantity": D("2")}],
    )

    catalog.merge_items(**plan(tablet, pack), dry_run=False)

    line = draft.lines.get()
    assert (line.item_id, line.quantity, line.qty_base) == (pack.pk, D("2"), D("8"))
    assert MinStock.objects.get(item=pack).min_qty == D("11")  # 2 упак = 8 таб + 3 таб


def test_items_with_stock_cannot_be_merged(pair) -> None:
    tablet, pack = pair
    store = Warehouse.objects.get(name="Основной склад")
    receipt = inventory.save_document(
        StockDocument(kind=StockDocument.Kind.RECEIPT, warehouse=store),
        [{"item_unit": tablet.units.get(), "quantity": D("10"), "price": D("50")}],
    )
    core.execute_document(receipt)

    with pytest.raises(catalog.CatalogError, match="остатки или движения на складе"):
        catalog.merge_items(**plan(tablet, pack), dry_run=True)

    core.rollback_document(receipt)  # откатили приход — теперь можно
    catalog.merge_items(**plan(tablet, pack), dry_run=False)
    assert receipt.lines.get().item_id == pack.pk


def test_wrong_plan_is_explained(pair) -> None:
    tablet, pack = pair
    wrong = plan(tablet, pack)
    wrong["units"][0]["ratio"] = D("1")  # «упак. = 1 таб.» — ошибка

    with pytest.raises(catalog.CatalogError, match="не может быть равна 1 таб"):
        catalog.merge_items(**wrong)

    wrong["units"] = wrong["units"][:1]
    with pytest.raises(catalog.CatalogError, match="Не указано, чем станет"):
        catalog.merge_items(**wrong)


def test_merge_api(pair, invoices) -> None:
    tablet, pack = pair
    api = APIClient()
    api.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    body = plan(tablet, pack)
    payload = {
        "main": str(body["main_id"]),
        "items": [str(i) for i in body["item_ids"]],
        "name": body["name"],
        "base_unit": str(body["base_unit_id"]),
        "units": [
            {"item_unit": str(u["item_unit"]), "unit": str(u["unit"]), "ratio": str(u["ratio"])}
            for u in body["units"]
        ],
    }

    preview = api.post("/api/catalog/items/merge/", {**payload, "dry_run": True}, format="json")
    done = api.post("/api/catalog/items/merge/", {**payload, "dry_run": False}, format="json")

    assert preview.status_code == 200 and "item" not in preview.json()
    assert done.status_code == 200, done.json()
    assert done.json()["item"]["base_unit_name"] == "таб."
    assert ItemUnit.objects.filter(item=pack).count() == 2


def test_merge_keeping_stock_in_packs(pair, invoices) -> None:
    """Как устроен справочник клиники: учёт в упаковках, таблетка — «меньше упак.», в 1 упак. — 4 таб."""
    tablet, pack = pair
    tab, upak = Unit.objects.get(name="таб."), Unit.objects.get(name="упак.")

    catalog.merge_items(
        pack.pk,
        [pack.pk, tablet.pk],
        "Пинпрамиль 4мг/10мг для кошек и котят (0,5–2 кг)",
        upak.pk,
        [
            {"item_unit": pack.units.get().pk, "unit": upak.pk, "ratio": D("1")},
            {"item_unit": tablet.units.get().pk, "unit": tab.pk, "ratio": D("0.25")},
        ],
        dry_run=False,
    )

    main = Item.objects.get(pk=pack.pk)
    assert main.base_unit == upak
    assert sorted((u.unit.name, u.ratio, u.price) for u in main.units.all()) == [
        ("таб.", D("0.25"), D("110")),
        ("упак.", D("1"), D("425")),
    ]
    lines = {line.item_unit.unit.name: line for line in InvoiceLine.objects.filter(item=main)}
    assert (lines["таб."].quantity, lines["таб."].qty_base) == (D("2"), D("0.5"))  # 2 таб = ½ упак
    assert (lines["упак."].quantity, lines["упак."].qty_base) == (D("1"), D("1"))
