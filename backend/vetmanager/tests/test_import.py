"""Перенос из VetManager: справочники, группы, товары и услуги.

API не вызывается — в тестах подставляются ответы, как их отдаёт VetManager.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from catalog.models import Item, Kind
from vetmanager import client, services
from vetmanager.models import Imported

D = Decimal

# В VetManager единицы часто задвоены: «шт», «Шт.», «штука» — всё это одна «шт.».
UNITS = [
    {"id": "1", "title": "шт"},
    {"id": "2", "title": "упаковка"},
    {"id": "3", "title": "Услуга"},
    {"id": "4", "title": "шт."},
    {"id": "5", "title": "штука"},
    {"id": "6", "title": "лоток"},
]
GROUPS = [
    {"id": "10", "title": "Препараты"},
    {"id": "11", "title": "препараты "},  # то же самое другим написанием
    {"id": "12", "title": "Приём"},
]
GOODS = [
    {
        "id": "100",
        "title": "Цефтриаксон 1 г",
        "group_id": "11",
        "unit_storage_id": "1",
        "is_warehouse_account": "1",
        "code": "A-1",
        "barcode": "4600001",
        "status": "ACTIVE",
    },
    {
        "id": "101",
        "title": "Первичный приём",
        "group_id": "12",
        "unit_storage_id": "3",
        "is_warehouse_account": "0",
        "status": "ACTIVE",
    },
    {"id": "102", "title": "", "group_id": "11", "unit_storage_id": "1"},
]
PRICES = {
    "100": [
        {"good_id": "100", "unit_sale_id": "1", "price": "120.50", "coefficient": "1"},
        {"good_id": "100", "unit_sale_id": "2", "price": "1100", "coefficient": "10"},
    ],
    "101": [{"good_id": "101", "unit_sale_id": "3", "price": "900", "coefficient": "1"}],
}


@pytest.fixture
def imported(db):
    services.import_units(UNITS)
    services.import_item_groups(GROUPS)
    return services.import_items(GOODS, PRICES)


def test_goods_and_services(imported) -> None:
    drug = Item.objects.get(name="Цефтриаксон 1 г")
    service = Item.objects.get(name="Первичный приём")

    assert imported.created == 2 and len(imported.errors) == 1  # позиция без названия
    assert drug.kind == Kind.GOODS and drug.stock_tracked and drug.article == "A-1"
    assert drug.group.name == "Препараты" and drug.base_unit.name == "шт."
    assert {(u.unit.name, u.ratio, u.price) for u in drug.units.all()} == {
        ("шт.", D("1.000000"), D("120.50")),
        ("упак.", D("10.000000"), D("1100.00")),
    }
    assert service.kind == Kind.SERVICE and not service.stock_tracked
    assert service.units.get().price == D("900.00")


def test_second_run_changes_nothing(imported) -> None:
    again = services.import_items(GOODS, PRICES)

    assert (again.created, again.skipped) == (0, 2)
    assert Item.objects.filter(name="Цефтриаксон 1 г").count() == 1


def test_status_counts(imported) -> None:
    status = {row["step"]: row["imported"] for row in services.status()}

    assert status == {"units": 6, "item_groups": 3, "items": 2}


def test_fetch_pages_and_errors(monkeypatch) -> None:
    pages = [
        {"totalCount": 3, "good": [{"id": "1"}, {"id": "2"}]},
        {"totalCount": 3, "good": [{"id": "3"}]},
    ]
    monkeypatch.setattr(client, "PAGE_SIZE", 2)
    monkeypatch.setattr(client, "_request", lambda model, params: pages[params["offset"] // 2])

    assert [row["id"] for row in client.fetch("Good")] == ["1", "2", "3"]


def test_api_needs_right_and_reports_settings(db, django_user_model, settings) -> None:
    settings.VETMANAGER_URL = ""
    admin = APIClient()
    admin.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    plain = APIClient()
    plain.force_authenticate(django_user_model.objects.create_user(username="u", password="x"))

    status = admin.get("/api/vetmanager/status/")
    refused = plain.get("/api/vetmanager/status/")
    unknown = admin.post("/api/vetmanager/run/", {"step": "ничего"}, format="json")

    assert status.json()["configured"] is False
    assert [s["step"] for s in status.json()["steps"]] == ["units", "item_groups", "items"]
    assert refused.status_code == 403
    assert "Неизвестный шаг" in unknown.json()["non_field_errors"][0]


def test_run_step_uses_api(db, monkeypatch) -> None:
    monkeypatch.setattr(services, "used_units", lambda: UNITS)

    result = services.run_step("units")

    # Единицы в системе уже есть — они не создаются заново, а связываются.
    assert result.created + result.updated == len(UNITS)
    assert Imported.objects.filter(kind="unit").count() == len(UNITS)


def test_probe_shows_fields(db, monkeypatch, django_user_model) -> None:
    """«Что отдаёт VetManager» — поля и пример записи реального аккаунта."""
    monkeypatch.setattr(
        client, "_request", lambda model, params: {"totalCount": 7, "good": [GOODS[0]]}
    )
    api = APIClient()
    api.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))

    found = api.get("/api/vetmanager/probe/?model=Good&count=1").json()

    assert found["total"] == 7 and "is_warehouse_account" in found["fields"]
    assert found["rows"][0]["title"] == "Цефтриаксон 1 г"
