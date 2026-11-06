"""Отделения: списание расходников с основного склада на отделение, отчёт по отделениям,
итоги остатков по складам."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from core import services as core
from inventory import services as inventory
from inventory.models import Department, StockDocument, Warehouse

D = Decimal


@pytest.fixture
def main(db):
    return Warehouse.objects.get(name="Основной склад")


@pytest.fixture
def gloves(main):
    item = catalog.save_item(
        Item(kind=Kind.GOODS, name="Перчатки", group=ItemGroup.objects.get(name="Расходные материалы"), base_unit=Unit.objects.get(name="шт.")),
        [{"unit": Unit.objects.get(name="шт."), "price": D("20"), "barcode": "2000000000017"}],
    )  # fmt: skip
    core.execute_document(inventory.save_document(StockDocument(kind="receipt", warehouse=main),
                                                  [{"item_unit": item.units.get(), "quantity": D("100"), "price": D("8")}]))  # fmt: skip
    return item


def test_departments_exist(db) -> None:
    assert set(Department.objects.values_list("name", flat=True)) >= {
        "Хирургия",
        "Стационар",
        "Терапия",
        "Приёмная",
    }


def test_old_write_off_to_department_counts_as_consumption(main, gloves) -> None:
    """Списания на отделение, сделанные до складов отделений, остаются расходом в отчёте."""
    from inventory import departments

    surgery = Department.objects.get(name="Хирургия")
    unit = gloves.units.get()
    doc = core.execute_document(
        inventory.save_document(
            StockDocument(kind="write_off", warehouse=main, department=surgery),
            [{"item_unit": unit, "quantity": D("10")}],
        )
    )
    today = timezone.localdate()

    rows = departments.summary(today, today, surgery)
    journal = departments.journal(today, today, surgery)

    assert [(r["item_name"], r["consumed"], r["closing"], r["cost"]) for r in rows] == [
        ("Перчатки", D("10"), D("0"), D("80.00"))
    ]
    assert [(j["operation"], j["qty"]) for j in journal] == [("writeoff", D("-10"))]
    core.rollback_document(doc)
    assert departments.summary(today, today, surgery) == []


def test_api_warehouse_totals(main, gloves) -> None:
    api = APIClient()
    api.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))

    totals = api.get("/api/inventory/reports/warehouses/").json()

    assert [(t["warehouse_name"], t["positions"], t["cost"]) for t in totals] == [
        ("Основной склад", 1, "800.00")
    ]
