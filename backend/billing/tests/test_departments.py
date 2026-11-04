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


def test_write_off_to_department_and_report(main, gloves) -> None:
    surgery = Department.objects.get(name="Хирургия")
    therapy = Department.objects.get(name="Терапия")
    unit = gloves.units.get()

    inventory.department_writeoff(main, surgery, [{"item_unit": unit, "quantity": D("10")}])
    doc = inventory.department_writeoff(
        main, therapy, [{"item_unit": unit, "quantity": D("4")}], "санобработка"
    )
    today = timezone.localdate()

    rows = inventory.department_consumption(today, today)

    assert doc.department == therapy and doc.reason == "санобработка"
    assert [(r["department_name"], r["qty"], r["cost"]) for r in rows] == [
        ("Терапия", D("4.000"), D("32.00")),
        ("Хирургия", D("10.000"), D("80.00")),
    ]
    assert inventory.available(gloves, main) == D("86")
    assert [
        r["department_name"] for r in inventory.department_consumption(today, today, surgery)
    ] == ["Хирургия"]
    core.rollback_document(doc)
    assert [r["department_name"] for r in inventory.department_consumption(today, today)] == [
        "Хирургия"
    ]


def test_write_off_needs_department(main, gloves) -> None:
    with pytest.raises(inventory.StockError, match="отделение"):
        inventory.department_writeoff(
            main, None, [{"item_unit": gloves.units.get(), "quantity": D("1")}]
        )


def test_api_writeoff_reports_and_cost_visibility(main, gloves) -> None:
    api = APIClient()
    api.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    surgery = Department.objects.get(name="Хирургия")

    scan = api.get(f"/api/inventory/transfer/?code=2000000000017&from={main.pk}").json()
    done = api.post("/api/inventory/department-writeoff/", {"from": str(main.pk), "department": str(surgery.pk),
                    "lines": [{"item_unit": scan["item_unit"], "quantity": "5"}]}, format="json")  # fmt: skip
    report = api.get("/api/inventory/reports/departments/").json()
    excel = api.get("/api/inventory/reports/departments/?export=xlsx")
    totals = api.get("/api/inventory/reports/warehouses/").json()

    assert scan["item_name"] == "Перчатки" and scan["on_target"] == "0"
    assert done.status_code == 201
    assert report == [{"department": str(surgery.pk), "department_name": "Хирургия", "item": str(gloves.pk), "item_name": "Перчатки",
                       "unit": "шт.", "qty": "5.000", "cost": "40.00"}]  # fmt: skip
    assert excel["Content-Type"].startswith("application/vnd.openxml")
    assert [(t["warehouse_name"], t["positions"], t["cost"]) for t in totals] == [
        ("Основной склад", 1, "760.00")
    ]
