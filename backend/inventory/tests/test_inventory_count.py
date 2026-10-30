"""Инвентаризация, возврат поставщику, минимальные остатки, сводка."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from core import services as core
from core.models import Counterparty
from inventory import services
from inventory.models import StockDocument, Warehouse
from inventory.services import StockError

D = Decimal
K = StockDocument.Kind


@pytest.fixture
def main(db):
    return Warehouse.objects.get(name="Основной склад")


@pytest.fixture
def drug(db):
    return catalog.save_item(
        Item(
            kind=Kind.GOODS,
            name="Витамины",
            group=ItemGroup.objects.get(name="Препараты"),
            base_unit=Unit.objects.get(name="таб."),
        ),
        [
            {"unit": Unit.objects.get(name="таб."), "price": D("3")},
            {"unit": Unit.objects.get(name="упак."), "ratio": D("10"), "price": D("25")},
        ],
    )


def receive(warehouse, item, qty, price="1", series="", expiry=None):
    doc = services.save_document(
        StockDocument(kind=K.RECEIPT, warehouse=warehouse),
        [
            {
                "item_unit": item.units.get(unit__name="таб."),
                "quantity": D(qty),
                "price": D(price),
                "series": series,
                "expiry_date": expiry,
            }
        ],
    )
    return core.execute_document(doc)


def test_fill_then_correct_shortage_and_surplus(drug, main) -> None:
    receive(main, drug, "10", series="A")
    receive(main, drug, "5", series="B")
    doc = services.fill_inventory(
        services.save_document(StockDocument(kind=K.INVENTORY, warehouse=main), [])
    )

    lines = list(doc.lines.order_by("batch__series"))
    assert [(line.qty_expected, line.quantity) for line in lines] == [
        (D("10.000"), D("10.000")),
        (D("5.000"), D("5.000")),
    ]

    payload = [{"item_unit": line.item_unit, "quantity": q, "batch": line.batch, "qty_expected": line.qty_expected}
               for line, q in zip(lines, (D("8"), D("6")), strict=True)]  # fmt: skip
    payload.append(
        {"item_unit": drug.units.get(unit__name="упак."), "quantity": D("1"), "price": D("20")}
    )  # нашли коробку
    core.execute_document(services.save_document(doc, payload))

    stock = {s.batch.series or "новая": s.qty for s in services.batch_stock(drug, main)}
    assert stock == {"A": D("8.000"), "B": D("6.000"), "новая": D("10.000")}
    assert services.batch_stock(drug, main)[-1].batch.cost_per_base == D("2.00")


def test_difference_counts_against_stock_at_execution(drug, main) -> None:
    receive(main, drug, "10")
    doc = services.fill_inventory(
        services.save_document(StockDocument(kind=K.INVENTORY, warehouse=main), [])
    )
    sale = services.save_document(
        StockDocument(kind=K.WRITE_OFF, warehouse=main),
        [{"item_unit": drug.units.get(unit__name="таб."), "quantity": D("3")}],
    )
    core.execute_document(sale)  # продали после заполнения, но до пересчёта

    line = doc.lines.get()
    core.execute_document(
        services.save_document(
            doc,
            [
                {
                    "item_unit": line.item_unit,
                    "quantity": D("7"),
                    "batch": line.batch,
                    "qty_expected": line.qty_expected,
                }
            ],
        )
    )

    assert services.available(drug, main) == D("7")


def test_inventory_rollback_and_zero_counted(drug, main) -> None:
    receive(main, drug, "4")
    doc = services.fill_inventory(
        services.save_document(StockDocument(kind=K.INVENTORY, warehouse=main), [])
    )
    line = doc.lines.get()
    core.execute_document(
        services.save_document(
            doc, [{"item_unit": line.item_unit, "quantity": D("0"), "batch": line.batch}]
        )
    )
    assert services.available(drug, main) == D("0")

    core.rollback_document(doc)
    assert services.available(drug, main) == D("4")


def test_return_to_supplier(drug, main) -> None:
    receive(main, drug, "10")
    supplier = Counterparty.objects.create(name="Ветпром")
    doc = services.save_document(StockDocument(kind=K.RETURN, warehouse=main, counterparty=supplier),
                                 [{"item_unit": drug.units.get(unit__name="таб."), "quantity": D("4")}])  # fmt: skip

    core.execute_document(doc)

    assert doc.counterparty == supplier
    assert services.available(drug, main) == D("6")


def test_min_stock_and_summary(drug, main) -> None:
    today = timezone.localdate()
    receive(main, drug, "3", expiry=today + timedelta(days=30))
    receive(main, drug, "2", expiry=today - timedelta(days=1))

    services.set_min_stock(drug, D("10"))
    low = services.low_stock()

    assert [(r["item_name"], r["qty"], r["min_qty"]) for r in low] == [
        ("Витамины", D("5"), D("10"))
    ]
    assert services.summary() == {"expired": 1, "expiring": 1, "low": 1}
    services.set_min_stock(drug, D("0"))
    assert services.low_stock() == []
    with pytest.raises(StockError):
        services.set_min_stock(drug, D("-1"))
