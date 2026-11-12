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

    assert status == {
        "units": 6,
        "item_groups": 4,
        "items": 4,
        "species": 0,
        "clients": 0,
        "pets": 0,
    }


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
    assert [s["step"] for s in status.json()["steps"]] == [
        "units",
        "item_groups",
        "items",
        "species",
        "clients",
        "pets",
    ]
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


# --- Клиенты и питомцы (ответы боевого аккаунта) --------------------------------------

PET_TYPES = [{"id": 1, "title": "Собаки"}, {"id": 2, "title": "Кошки"}]
BREEDS = [
    {"id": 10, "title": "Метис", "pet_type_id": 1},
    {"id": 11, "title": "Британская", "pet_type_id": 2},
    {"id": 12, "title": "Без вида", "pet_type_id": 99},
]
CLIENTS = [
    {
        "id": 100,
        "last_name": "Пушкин",
        "first_name": "Александр",
        "middle_name": "Сергеевич",
        "cell_phone": "555098765",
        "home_phone": "",
        "work_phone": "312900900",
        "phone_prefix": "+996",
        "email": "pushkin@example.com",
        "address": "Жантошева 70",
        "apartment": "12",
        "city": "Бишкек",
        "zip": "720005",
        "discount": "5.0000000000",
        "note": "постоянный клиент",
        "in_blacklist": 0,
        "unsubscribe": 0,
        "status": "ACTIVE",
        "number_of_journal": "А-12",
        "passport_series": "AN1234567",
    },
    {
        "id": 101,
        "last_name": "",
        "first_name": "",
        "cell_phone": "700111222",
        "status": "ACTIVE",
        "in_blacklist": 1,
        "unsubscribe": 1,
        "discount": "0.0000000000",
    },
]
PETS = [
    {
        "id": 200,
        "alias": "Барсик",
        "owner_id": 100,
        "type_id": 2,
        "breed_id": 11,
        "sex": "male",
        "birthday": "2019-05-17",
        "chip_number": "643094",
        "weight": "4.5",
        "note": "боится машин",
        "status": "ACTIVE",
        "deathdate": "0000-00-00",
        "date_register": "2020-01-10",
        "lab_number": "77",
    },
    {
        "id": 201,
        "alias": "Рекс",
        "owner_id": 100,
        "type_id": 1,
        "breed_id": 10,
        "sex": "девочка",
        "birthday": "0000-00-00",
        "deathdate": "2025-03-01",
        "deathnote": "по возрасту",
        "weight": "0",
    },
    {"id": 202, "alias": "Ничей", "owner_id": 999, "type_id": 1, "breed_id": 10},
]


@pytest.fixture
def people(db):
    services.import_species(PET_TYPES, BREEDS)
    services.import_clients(CLIENTS)
    return services.import_pets(PETS)


def test_species_and_breeds(db) -> None:
    from clients.models import Breed, Species

    result = services.import_species(PET_TYPES, BREEDS)

    assert Species.objects.filter(name="Собаки").exists()
    assert Breed.objects.get(name="Британская").species.name == "Кошки"
    assert len(result.errors) == 1  # порода без своего вида


def test_clients_with_phones_and_fields(db) -> None:
    from clients.models import Client

    services.import_clients(CLIENTS)

    pushkin = Client.objects.get(last_name="Пушкин")
    assert (pushkin.first_name, pushkin.middle_name) == ("Александр", "Сергеевич")
    assert [(p.number, p.kind, p.is_primary) for p in pushkin.phones.all()] == [
        ("+996555098765", "mobile", True),
        ("+996312900900", "work", False),
    ]
    assert pushkin.discount_percent == D("5.00") and pushkin.city.name == "Бишкек"
    assert pushkin.house == "Жантошева 70 12" and pushkin.description == "постоянный клиент"
    assert pushkin.journal_number == "А-12" and pushkin.passport == "AN1234567"
    # Клиент без ФИО: фамилией становится телефон — карточку видно и можно поправить.
    nameless = Client.objects.exclude(pk=pushkin.pk).get()
    assert nameless.last_name == "700111222" and nameless.in_blacklist and nameless.no_mailing


def test_pets_with_species_breed_and_death(people) -> None:
    from clients.models import Pet

    barsik = Pet.objects.get(name="Барсик")
    rex = Pet.objects.get(name="Рекс")

    assert people.created == 2 and len(people.errors) == 1  # питомец без перенесённого владельца
    assert barsik.species.name == "Кошки" and barsik.breed.name == "Британская"
    assert barsik.sex == Pet.Sex.MALE and str(barsik.birth_date) == "2019-05-17"
    assert barsik.chip_number == "643094" and barsik.weights.get().weight == D("4.500")
    assert rex.sex == Pet.Sex.FEMALE and rex.birth_date is None  # «0000-00-00» — пусто
    assert rex.status == Pet.Status.DEAD and str(rex.death_date) == "2025-03-01"
    assert "по возрасту" in rex.notes


def test_people_second_run_changes_nothing(people) -> None:
    from clients.models import Client, Pet

    again = services.import_pets(PETS)

    assert again.created == 0 and again.skipped == 2
    assert Client.objects.filter(last_name="Пушкин").count() == 1 and Pet.objects.count() == 2


# --- Случаи из боевой выгрузки (194 позиции не переносились) ---------------------------


def test_sale_unit_with_coefficient_one_is_the_base_unit(db) -> None:
    """«Габапентин-АСТРА»: учёт в «шт.», единица продажи «упак.» с коэффициентом 1 —
    это та же единица под другим названием, отдельной её заводить нельзя."""
    services.import_units([{"id": "1", "title": "шт"}, {"id": "2", "title": "упак."}])
    goods = [
        {
            "id": 500,
            "title": "Габапентин-АСТРА таблетки 50 мг",
            "unit_storage_id": 1,
            "is_warehouse_account": 1,
            "is_active": 1,
            "group": {"id": 66, "title": "Препараты", "is_service": 0},
            "unitStorage": {"id": 1, "title": "шт"},
            "goodSaleParams": [
                {
                    "good_id": 500,
                    "price": "290.0000000000",
                    "coefficient": 1,
                    "unit_sale_id": 2,
                    "status": "active",
                    "is_last": 1,
                }
            ],
        }
    ]

    result = services.import_items(goods)

    item = Item.objects.get(name="Габапентин-АСТРА таблетки 50 мг")
    assert result.created == 1 and not result.errors
    assert [(u.unit.name, u.price) for u in item.units.all()] == [("шт.", D("290.00"))]


def test_price_outside_limits_keeps_price_and_drops_limits(db) -> None:
    """«Кастрация кота»: цену подняли, а максимум в VetManager остался прежним.
    Цена важнее — границы не переносим, позиция сохраняется."""
    goods = [
        {
            "id": 501,
            "title": "Кастрация кота",
            "unit_storage_id": 7,
            "is_warehouse_account": 0,
            "is_active": 1,
            "group": {"id": 9, "title": "Услуги", "is_service": 1},
            "unitStorage": {"id": 7, "title": "усл."},
            "goodSaleParams": [
                {
                    "good_id": 501,
                    "price": "3500.0000000000",
                    "coefficient": 1,
                    "unit_sale_id": 7,
                    "min_price": "1000.0000000000",
                    "max_price": "2000.0000000000",
                    "status": "active",
                    "is_last": 1,
                }
            ],
        }
    ]

    result = services.import_items(goods)

    unit = Item.objects.get(name="Кастрация кота").units.get()
    assert result.created == 1 and not result.errors
    assert unit.price == D("3500.00") and unit.price_min == D("1000.00") and unit.price_max is None


def test_sane_limits_are_kept(db) -> None:
    goods = [
        {
            "id": 502,
            "title": "Приём врача",
            "unit_storage_id": 7,
            "is_warehouse_account": 0,
            "is_active": 1,
            "group": {"id": 9, "title": "Услуги", "is_service": 1},
            "unitStorage": {"id": 7, "title": "усл."},
            "goodSaleParams": [
                {
                    "good_id": 502,
                    "price": "900.0000000000",
                    "coefficient": 1,
                    "unit_sale_id": 7,
                    "min_price": "800.0000000000",
                    "max_price": "1200.0000000000",
                    "status": "active",
                    "is_last": 1,
                }
            ],
        }
    ]

    services.import_items(goods)

    unit = Item.objects.get(name="Приём врача").units.get()
    assert (unit.price_min, unit.price_max) == (D("800.00"), D("1200.00"))


def test_status_counts_species_and_breeds_apart(db) -> None:
    """В шаге «Виды и породы» считаются и виды, и породы: иначе 433 породы не видно."""
    services.import_species(PET_TYPES, BREEDS)

    row = next(r for r in services.status() if r["step"] == "species")

    assert row["imported"] == 4  # 2 вида + 2 породы (третья — без своего вида)
    assert row["detail"] == "2 видов, 2 пород"
