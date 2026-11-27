"""Один штрихкод — разные сроки (ADR-025).

Штрихкод говорит, что это за товар; срок и серия — какая это партия. Пачки одного товара
с разными сроками — разные партии, а повторный пересчёт той же пачки не заводит двойника.
"""

from datetime import date
from decimal import Decimal

import pytest

from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from core import services as core
from inventory import services
from inventory.models import StockDocument, Warehouse

D = Decimal
K = StockDocument.Kind
MARCH, AUGUST = date(2027, 3, 28), date(2027, 8, 28)


@pytest.fixture
def main(db):
    return Warehouse.objects.get(name="Основной склад")


@pytest.fixture
def drug(db):
    return catalog.save_item(
        Item(
            kind=Kind.GOODS,
            name="Синулокс 50 мг",
            group=ItemGroup.objects.get(name="Препараты"),
            base_unit=Unit.objects.get(name="таб."),
        ),
        [
            {"unit": Unit.objects.get(name="таб."), "price": D("90")},
            {
                "unit": Unit.objects.get(name="упак."),
                "ratio": D("10"),
                "price": D("800"),
                "barcode": "5414736043517",
            },
        ],
    )


def pack(drug, qty="1", **extra):
    return {"item_unit": drug.units.get(unit__name="упак."), "quantity": D(qty), **extra}


def count(main, lines):
    doc = services.save_document(StockDocument(kind=K.INVENTORY, warehouse=main), lines)
    return core.execute_document(doc)


def stock_by_expiry(drug, main):
    return {s.batch.expiry_date: s.qty for s in services.batch_stock(drug, main)}


def test_same_barcode_different_expiry_makes_two_batches(drug, main) -> None:
    count(main, [pack(drug, expiry_date=MARCH, price=D("500")), pack(drug, expiry_date=AUGUST)])

    assert stock_by_expiry(drug, main) == {MARCH: D("10.000"), AUGUST: D("10.000")}


def test_same_expiry_in_two_lines_adds_up(drug, main) -> None:
    count(main, [pack(drug, expiry_date=MARCH), pack(drug, "2", expiry_date=MARCH)])

    assert stock_by_expiry(drug, main) == {MARCH: D("30.000")}


def test_recount_by_expiry_corrects_existing_batch_without_twin(drug, main) -> None:
    count(main, [pack(drug, "3", expiry_date=MARCH, price=D("500"))])
    count(main, [pack(drug, "2", expiry_date=MARCH)])  # пересчитали: одной пачки нет

    stock = services.batch_stock(drug, main)
    assert [(s.batch.expiry_date, s.qty) for s in stock] == [(MARCH, D("20.000"))]

    count(main, [pack(drug, "4", expiry_date=MARCH)])  # нашли ещё две
    stock = services.batch_stock(drug, main)
    assert [(s.batch.expiry_date, s.qty) for s in stock] == [(MARCH, D("40.000"))]
    assert stock[0].batch.cost_per_base == D("50.00")  # закупочная цена старой партии


def test_expiry_without_series_matches_batch_with_series(drug, main) -> None:
    count(main, [pack(drug, expiry_date=MARCH, series="842166", price=D("500"))])
    count(main, [pack(drug, "2", expiry_date=MARCH)])  # обычный штрихкод: серии нет

    stock = services.batch_stock(drug, main)
    assert [(s.batch.series, s.qty) for s in stock] == [("842166", D("20.000"))]


def test_different_series_is_a_different_batch(drug, main) -> None:
    count(main, [pack(drug, expiry_date=MARCH, series="A1", price=D("500"))])
    count(main, [pack(drug, expiry_date=MARCH, series="B2", price=D("500"))])

    assert {s.batch.series: s.qty for s in services.batch_stock(drug, main)} == {
        "B2": D("10.000"),
        "A1": D("10.000"),
    }


def test_rollback_keeps_matched_batch(drug, main) -> None:
    count(main, [pack(drug, "3", expiry_date=MARCH, price=D("500"))])
    second = count(main, [pack(drug, "2", expiry_date=MARCH)])

    core.rollback_document(second)

    assert stock_by_expiry(drug, main) == {MARCH: D("30.000")}


# --- Код с упаковки --------------------------------------------------------------

CRYPTO = "A" * 44


def test_parse_datamatrix_with_expiry_and_series() -> None:
    parsed = services.parse_gs1("01054147360435171727110010842166")

    assert parsed["ean"] == "5414736043517"
    assert parsed["expiry"] == date(2027, 11, 28)  # день 00 — до конца месяца
    assert parsed["batch"] == "842166"


@pytest.mark.parametrize(
    "code",
    [
        "0104601234567893215Abc12DeF3gH4\x1d91EE06\x1d92" + CRYPTO,  # с разделителями
        "0104601234567893215Abc12DeF3gH491EE0692" + CRYPTO,  # сканер склеил в строку
        "0104601234567893215Фис12ВуА3пР491УУ0692" + "Ф" * 44,  # русская раскладка
        "]d20104601234567893215Abc12DeF3gH4\x1d93EE06",  # префикс и короткий код
    ],
)
def test_parse_marking_code(code) -> None:
    parsed = services.parse_gs1(code)

    assert parsed["ean"] == "4601234567893"
    assert parsed["serial"] == "5Abc12DeF3gH4"
    assert parsed["expiry"] is None and parsed["batch"] == ""


def test_plain_barcode_is_not_gs1() -> None:
    assert services.parse_gs1("5414736043517") is None
