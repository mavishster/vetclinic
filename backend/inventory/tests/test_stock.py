"""Склад: приход с партиями, расход по сроку годности, перемещение, откаты, стыки для счетов."""

from datetime import date
from decimal import Decimal

import pytest

from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from core import services as core
from core.models import Counterparty, DocumentError
from inventory import services
from inventory.models import StockDocument, Warehouse
from inventory.services import StockError

D = Decimal
K = StockDocument.Kind


@pytest.fixture
def drug(db):
    """Витамины: учёт в таблетках, упаковка = 216 таблеток."""
    return catalog.save_item(
        Item(
            kind=Kind.GOODS,
            name="Витамины 8в1",
            group=ItemGroup.objects.get(name="Препараты"),
            base_unit=Unit.objects.get(name="таб."),
        ),
        [
            {"unit": Unit.objects.get(name="таб."), "ratio": D("1"), "price": D("3")},
            {
                "unit": Unit.objects.get(name="упак."),
                "ratio": D("216"),
                "price": D("600"),
                "for_purchase": True,
                "barcode": "4601234567890",
            },
        ],
    )


@pytest.fixture
def main(db):
    return Warehouse.objects.get(name="Основной склад")


def unit(item, name):
    return item.units.get(unit__name=name)


def receipt(warehouse, lines, **fields):
    doc = services.save_document(
        StockDocument(kind=K.RECEIPT, warehouse=warehouse, **fields), lines
    )
    return core.execute_document(doc)


def test_receipt_creates_batch_with_cost_per_base_and_marks_tracked(drug, main) -> None:
    supplier = Counterparty.objects.create(name="Ветпром")
    doc = receipt(main, [{"item_unit": unit(drug, "упак."), "quantity": D("2"), "price": D("432"),
                          "series": "A1", "expiry_date": date(2027, 6, 1)}], counterparty=supplier)  # fmt: skip

    line = doc.lines.get()
    assert line.qty_base == D("432")
    assert line.batch.cost_per_base == D("2.00")
    assert services.available(drug, main) == D("432")
    drug.refresh_from_db()
    assert drug.stock_tracked
    assert doc.number.endswith("-000001")


def test_write_off_takes_nearest_expiry_first_across_batches(drug, main) -> None:
    receipt(
        main,
        [
            {
                "item_unit": unit(drug, "таб."),
                "quantity": D("10"),
                "price": D("2"),
                "series": "LATE",
                "expiry_date": date(2028, 1, 1),
            }
        ],
    )
    receipt(
        main,
        [
            {
                "item_unit": unit(drug, "таб."),
                "quantity": D("5"),
                "price": D("1"),
                "series": "SOON",
                "expiry_date": date(2027, 1, 1),
            }
        ],
    )

    write_off = services.save_document(
        StockDocument(kind=K.WRITE_OFF, warehouse=main, reason="Бой"),
        [{"item_unit": unit(drug, "таб."), "quantity": D("8")}],
    )
    core.execute_document(write_off)

    left = {s.batch.series: s.qty for s in services.batch_stock(drug, main)}
    assert left == {"LATE": D("7")}


def test_not_enough_stock_is_explained_and_nothing_written(drug, main) -> None:
    receipt(main, [{"item_unit": unit(drug, "таб."), "quantity": D("3"), "price": D("2")}])
    doc = services.save_document(
        StockDocument(kind=K.WRITE_OFF, warehouse=main),
        [{"item_unit": unit(drug, "таб."), "quantity": D("5")}],
    )

    with pytest.raises(StockError, match="нужно 5, есть 3"):
        core.execute_document(doc)
    assert services.available(drug, main) == D("3")


def test_transfer_moves_same_batch_and_cost(drug, main) -> None:
    storage = Warehouse.objects.create(name="Склад хранения", kind=Warehouse.Kind.STORAGE)
    receipt(storage, [{"item_unit": unit(drug, "упак."), "quantity": D("1"), "price": D("216")}])

    move = services.save_document(StockDocument(kind=K.TRANSFER, warehouse=storage, target_warehouse=main),
                                  [{"item_unit": unit(drug, "таб."), "quantity": D("50")}])  # fmt: skip
    core.execute_document(move)

    assert services.available(drug, storage) == D("166")
    assert services.available(drug, main) == D("50")
    assert services.batch_stock(drug, main)[0].batch.cost_per_base == D("1.00")


def test_transfer_needs_different_warehouses(drug, main) -> None:
    with pytest.raises(StockError, match="разными"):
        services.save_document(
            StockDocument(kind=K.TRANSFER, warehouse=main, target_warehouse=main), []
        )


def test_receipt_rollback_only_while_goods_untouched(drug, main) -> None:
    doc = receipt(main, [{"item_unit": unit(drug, "таб."), "quantity": D("10"), "price": D("2")}])
    sale = services.save_document(
        StockDocument(kind=K.WRITE_OFF, warehouse=main),
        [{"item_unit": unit(drug, "таб."), "quantity": D("1")}],
    )
    core.execute_document(sale)

    with pytest.raises(StockError, match="уже продана"):
        core.rollback_document(doc)

    core.rollback_document(sale)
    core.rollback_document(doc)
    assert services.available(drug, main) == D("0")
    assert services.batch_stock(drug) == []


def test_line_rules(drug, main) -> None:
    service = catalog.save_item(
        Item(
            kind=Kind.SERVICE,
            name="Приём",
            group=ItemGroup.objects.get(name="Приём и консультации"),
            base_unit=Unit.objects.get(name="усл."),
        ),
        [{"unit": Unit.objects.get(name="усл."), "price": D("500")}],
    )

    with pytest.raises(StockError, match="не товар"):
        services.save_document(
            StockDocument(kind=K.RECEIPT, warehouse=main),
            [{"item_unit": service.units.get(), "quantity": D("1"), "price": D("1")}],
        )
    with pytest.raises(StockError, match="закупочную цену"):
        services.save_document(
            StockDocument(kind=K.RECEIPT, warehouse=main),
            [{"item_unit": unit(drug, "таб."), "quantity": D("1")}],
        )
    with pytest.raises(StockError, match="отрицательной"):
        services.save_document(
            StockDocument(kind=K.RECEIPT, warehouse=main),
            [{"item_unit": unit(drug, "таб."), "quantity": D("1"), "price": D("-5")}],
        )
    with pytest.raises(StockError, match="больше нуля"):
        services.save_document(
            StockDocument(kind=K.WRITE_OFF, warehouse=main),
            [{"item_unit": unit(drug, "таб."), "quantity": D("0")}],
        )


def test_executed_document_is_locked(drug, main) -> None:
    doc = receipt(main, [{"item_unit": unit(drug, "таб."), "quantity": D("1"), "price": D("2")}])

    with pytest.raises(DocumentError):
        doc.comment = "правка"
        doc.save()


def test_write_off_and_reverse_for_other_modules(drug, main) -> None:
    receipt(main, [{"item_unit": unit(drug, "таб."), "quantity": D("10"), "price": D("2")}])
    source = core.execute_document(
        services.save_document(
            StockDocument(kind=K.WRITE_OFF, warehouse=main),
            [{"item_unit": unit(drug, "таб."), "quantity": D("1")}],
        )
    )

    written = services.write_off([{"item": drug, "qty_base": D("4"), "warehouse": main}], source)
    assert [(w.qty, w.cost_per_base) for w in written] == [(D("4"), D("2.00"))]
    assert services.available(drug, main) == D("5")

    services.reverse(source)
    assert services.available(drug, main) == D("10")


def test_barcode_finds_package_unit(drug) -> None:
    found = catalog.find_by_barcode("4601234567890")

    assert found.unit.name == "упак." and found.ratio == D("216")


def test_balances_report(drug, main) -> None:
    receipt(
        main,
        [
            {
                "item_unit": unit(drug, "таб."),
                "quantity": D("10"),
                "price": D("2"),
                "series": "S1",
                "expiry_date": date(2027, 1, 1),
            }
        ],
    )

    rows = services.balances(search="витамины")

    assert [(r["series"], r["qty"], r["cost"]) for r in rows] == [
        ("S1", D("10.000"), D("20.00000"))
    ]
