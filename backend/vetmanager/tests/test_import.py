"""Перенос из VetManager: справочники, группы, товары и услуги.

API не вызывается — в тестах подставляются ответы, как их отдаёт VetManager.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from catalog.models import Item, ItemGroup, Kind
from vetmanager import client, services
from vetmanager.models import Imported

D = Decimal

# В VetManager единицы часто задвоены: «шт», «Шт.», «штука» — всё это одна «шт.».
# Ответы взяты с боевого аккаунта клиники: VetManager отдаёт позицию вместе с группой,
# единицей учёта и ценами, а «не задано» хранит нулями.
GOODS = [
    {
        "id": 1,
        "group_id": 45,
        "title": "Вакцина Нобивак DHPPI",
        "unit_storage_id": 5,
        "is_warehouse_account": 1,
        "is_active": 1,
        "code": "",
        "is_call": 0,
        "is_for_sale": 1,
        "for_combination": 0,
        "barcode": "",
        "description": "Живая, сухая вакцина для собак.",
        "prime_cost": "0.0000000000",
        "is_recipe": 0,
        "group": {"id": 45, "title": "Вакцины", "is_service": 0, "markup": None},
        "unitStorage": {"id": 5, "title": "доза", "status": "active"},
        "goodSaleParams": [
            {
                "id": 1,
                "good_id": 1,
                "price": "1500.0000000000",
                "coefficient": 1,
                "unit_sale_id": 5,
                "min_price": "0.0000000000",
                "max_price": "0.0000000000",
                "barcode": "",
                "status": "active",
                "markup": "0.0000000000",
                "price_formation": "fixed",
                "is_last": 1,
            }
        ],
    },
    {
        "id": 2,
        "group_id": 66,
        "title": "Энрофлоксацин",
        "unit_storage_id": 4,
        "is_warehouse_account": 1,
        "is_active": 1,
        "code": "A-7",
        "is_call": 0,
        "is_for_sale": 1,
        "for_combination": 0,
        "barcode": "4600001",
        "description": "антибиотик",
        "prime_cost": "30.0000000000",
        "group": {"id": 66, "title": "Препараты", "is_service": 0, "markup": None},
        "unitStorage": {"id": 4, "title": "мл", "status": "active"},
        "goodSaleParams": [
            {
                "id": 2,
                "good_id": 2,
                "price": "50.0000000000",
                "coefficient": 1,
                "unit_sale_id": 4,
                "min_price": "0.0000000000",
                "max_price": "0.0000000000",
                "status": "active",
                "markup": "0.0000000000",
                "price_formation": "fixed",
                "is_last": 1,
            },
            {
                "id": 3,
                "good_id": 2,
                "price": "45.0000000000",
                "coefficient": 1,
                "unit_sale_id": 4,
                "status": "active",
                "price_formation": "fixed",
                "is_last": 0,
            },  # прежняя цена
        ],
    },
    {
        "id": 3,
        "group_id": 9,
        "title": "Первичный приём",
        "unit_storage_id": 7,
        "is_warehouse_account": 0,
        "is_active": 1,
        "is_for_sale": 1,
        "is_call": 1,
        "prime_cost": "0.0000000000",
        "group": {"id": 9, "title": "Услуги", "is_service": 1, "markup": None},
        "unitStorage": {"id": 7, "title": "Услуга", "status": "active"},
        "goodSaleParams": [
            {
                "id": 4,
                "good_id": 3,
                "price": "900.0000000000",
                "coefficient": 1,
                "unit_sale_id": 7,
                "min_price": "800.0000000000",
                "max_price": "1200.0000000000",
                "status": "active",
                "price_formation": "fixed",
                "is_last": 1,
            }
        ],
    },
    {
        "id": 4,
        "group_id": 66,
        "title": "",
        "unit_storage_id": 4,
        "is_active": 1,
        "group": {"id": 66, "title": "Препараты", "is_service": 0},
    },
    {
        "id": 5,
        "group_id": 66,
        "title": "Корм с наценкой",
        "unit_storage_id": 1,
        "is_warehouse_account": 1,
        "is_active": 0,
        "is_for_sale": 1,
        "prime_cost": "100.0000000000",
        "group": {"id": 66, "title": "Препараты", "is_service": 0},
        "unitStorage": {"id": 1, "title": "шт", "status": "active"},
        "goodSaleParams": [
            {
                "id": 5,
                "good_id": 5,
                "price": "0.0000000000",
                "coefficient": 1,
                "unit_sale_id": 1,
                "markup": "40.0000000000",
                "price_formation": "markup",
                "status": "active",
                "is_last": 1,
            }
        ],
    },
]
GROUPS = [
    {"id": 9, "title": "Услуги", "is_service": 1, "markup": None},
    {"id": 45, "title": "Вакцины", "is_service": 0, "markup": None},
    {"id": 66, "title": "Препараты", "is_service": 0, "markup": "25.0000000000"},
    {"id": 67, "title": "препараты ", "is_service": 0, "markup": None},  # то же другим написанием
]
UNITS = [
    {"id": "1", "title": "шт"},
    {"id": "4", "title": "мл"},
    {"id": "5", "title": "доза"},
    {"id": "7", "title": "Услуга"},
    {"id": "8", "title": "штука"},
    {"id": "9", "title": "лоток"},
]


@pytest.fixture
def imported(db):
    services.import_units(UNITS)
    services.import_item_groups(GROUPS)
    return services.import_items(GOODS)


def test_goods_and_services(imported) -> None:
    vaccine = Item.objects.get(name="Вакцина Нобивак DHPPI")
    drug = Item.objects.get(name="Энрофлоксацин")
    service = Item.objects.get(name="Первичный приём")

    assert imported.created == 4 and len(imported.errors) == 1  # позиция без названия
    # Вид берётся из группы (is_service), а не из складского учёта.
    assert vaccine.kind == Kind.GOODS and vaccine.group.name == "Вакцины"
    assert vaccine.base_unit.name == "доза" and vaccine.units.get().price == D("1500.00")
    assert vaccine.description.startswith("Живая, сухая вакцина")
    assert vaccine.manual_cost is None  # prime_cost 0 — значит «не задано»
    assert drug.manual_cost == D("30.00") and drug.article == "A-7" and drug.barcode == "4600001"
    assert drug.units.count() == 1 and drug.units.get().price == D(
        "50.00"
    )  # прежняя цена не берётся
    assert service.kind == Kind.SERVICE and not service.stock_tracked and service.is_call
    assert service.base_unit.name == "усл."  # «Услуга» сведена к нашей единице
    unit = service.units.get()
    assert (unit.price, unit.price_min, unit.price_max) == (D("900.00"), D("800.00"), D("1200.00"))


def test_markup_price_and_inactive(imported) -> None:
    food = Item.objects.get(name="Корм с наценкой")

    assert not food.is_active  # is_active 0
    unit = food.units.get()
    assert unit.pricing == "markup" and unit.markup_percent == D("40.00") and unit.price is None


def test_group_markup_and_kind(imported) -> None:
    assert ItemGroup.objects.get(name="Препараты", kind=Kind.GOODS).markup_percent == D("25.00")
    assert ItemGroup.objects.get(name="Услуги").kind == Kind.SERVICE
    assert ItemGroup.objects.filter(name__iexact="препараты").count() == 1  # написания сведены


def test_second_run_changes_nothing(imported) -> None:
    again = services.import_items(GOODS)

    assert (again.created, again.skipped) == (0, 4)
    assert Item.objects.filter(name="Энрофлоксацин").count() == 1


def test_status_counts(imported) -> None:
    status = {row["step"]: row["imported"] for row in services.status()}

    assert status == {"units": 6, "item_groups": 4, "items": 4}


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
    assert found["rows"][0]["title"] == "Вакцина Нобивак DHPPI"
