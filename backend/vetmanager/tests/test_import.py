"""Перенос из VetManager: справочники, группы, товары и услуги.

API не вызывается — в тестах подставляются ответы, как их отдаёт VetManager.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
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
        "doctors": 0,
        "diagnoses": 0,
        "visits": 0,
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
        "doctors",
        "diagnoses",
        "visits",
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
        "phone_prefix": "",  # код страны в выгрузке часто пуст
        "email": "pushkin@example.com",
        "address": "70",
        "apartment": "кв. 12",
        "city": "Бишкек",
        "street_id": 55,
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
    {
        "id": 203,
        "alias": "Чомар",
        "owner_id": 100,
        "type_id": 2,
        "breed_id": 11,
        "sex": "Кастрирован",  # в VetManager пол и стерилизация — одно поле
        "status": "DELETED",  # питомец не активен
        "chip_number": "990000000072581",
    },
    {
        "id": 204,
        "alias": "Муся",
        "owner_id": 100,
        "type_id": 2,
        "breed_id": 11,
        "sex": "Стерилизована",
    },
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
    assert pushkin.house == "70 кв. 12" and pushkin.description == "постоянный клиент"
    assert pushkin.journal_number == "А-12" and pushkin.passport == "AN1234567"
    # Клиент без ФИО: фамилией становится телефон — карточку видно и можно поправить.
    nameless = Client.objects.exclude(pk=pushkin.pk).get()
    assert nameless.last_name == "700111222" and nameless.in_blacklist and nameless.no_mailing


def test_pets_with_species_breed_and_death(people) -> None:
    from clients.models import Pet

    barsik = Pet.objects.get(name="Барсик")
    rex = Pet.objects.get(name="Рекс")

    assert people.created == 4 and len(people.errors) == 1  # питомец без перенесённого владельца
    assert barsik.species.name == "Кошки" and barsik.breed.name == "Британская"
    assert barsik.sex == Pet.Sex.MALE and str(barsik.birth_date) == "2019-05-17"
    assert barsik.chip_number == "643094" and barsik.weights.get().weight == D("4.500")
    assert rex.sex == Pet.Sex.FEMALE and rex.birth_date is None  # «0000-00-00» — пусто
    assert rex.status == Pet.Status.DEAD and str(rex.death_date) == "2025-03-01"
    assert "по возрасту" in rex.notes


def test_people_second_run_changes_nothing(people) -> None:
    """Повторный перенос не задваивает: те же записи обновляются, новых нет."""
    from clients.models import Client, Pet

    again = services.import_pets(PETS)

    assert again.created == 0 and again.updated == 4
    assert Client.objects.filter(last_name="Пушкин").count() == 1 and Pet.objects.count() == 4


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


# --- Врачи и медкарты -----------------------------------------------------------------

VM_USERS = [
    {
        "id": 3,
        "last_name": "Петрова",
        "first_name": "Анна",
        "middle_name": "",
        "is_active": 1,
        "phone": "555112233",
        "email": "petrova@clinic.kg",
    },
    {
        "id": 4,
        "last_name": "Сидоров",
        "first_name": "Пётр",
        "is_active": 0,
        "position": {"id": 2, "title": "Ассистент"},
        "cell_phone": "0700445566",
        "email": "не почта",
    },
    {"id": 5, "last_name": "Кассирова", "first_name": "Ольга", "is_active": 1},  # приёмов нет
]
# Типы приёмов и результаты лежат в общем справочнике ComboManualItem.
VM_DIAGNOSES = [
    {"id": 176, "title": "Абсцесс", "status": "ACTIVE"},
    {"id": 146, "title": "Отит наружный", "status": "ACTIVE"},
    {"id": 900, "title": "Старый диагноз", "status": "DELETED"},
]
COMBO_ITEMS = [
    {"id": 1, "title": "Первичный"},
    {"id": 2, "title": "Хирургия"},
    {"id": 9, "title": "Выздоровление"},
]
# Медкарты боевого аккаунта: описание, рекомендации, диагноз, вес и температура.
MEDICAL_CARDS = [
    {
        "id": 700,
        "patient_id": 200,
        "doctor_id": 3,
        "admission_type": 2,
        "meet_result_id": 9,
        "date_create": "2026-03-14 10:30:00",
        "description": "<p>Осмотр, t 38,9</p><script>alert(1)</script>",
        "recomendation": "<p>Повторно через 10 дней</p>",
        "diagnos": "176,146",  # номера из справочника диагнозов
        "diagnos_text": "Абсцесс, Отит наружный",
        "weight": "4.2000000000",
        "temperature": "38.9000000000",
        "status": "active",
    },
    {
        "id": 701,
        "patient_id": 200,
        "doctor_id": 99,  # такого врача нет даже в выгрузке
        "admission_type": 1,
        "date_create": "2026-04-02 09:00:00",
        "description": "Повторный осмотр",
        "weight": "0.0000000000",
        "diagnos": "0",
        "diagnos_text": "0",
    },
    {
        "id": 702,
        "patient_id": 999,
        "doctor_id": 3,
        "date_create": "2026-04-03 09:00:00",
        "description": "Питомца не переносили",
    },
    {
        "id": 703,
        "patient_id": 200,
        "doctor_id": 3,
        "date_create": "0000-00-00 00:00:00",
        "description": "Без даты",
    },
    {
        "id": 704,
        "patient_id": 200,
        "doctor_id": 3,
        "date_create": "2026-05-01 10:00:00",
        "description": "Удалённая медкарта",
        "status": "deleted",
    },
]


@pytest.fixture
def visits(people, django_user_model):
    django_user_model.objects.create_user(
        username="petrova", last_name="Петрова", first_name="Анна"
    )
    services.import_doctors(VM_USERS, only_with_visits=False)
    services.import_visit_purposes(COMBO_ITEMS)
    services.import_diagnoses(VM_DIAGNOSES)
    return services.import_visits(MEDICAL_CARDS, COMBO_ITEMS)


def test_doctors_link_known_and_create_missing(db, django_user_model) -> None:
    """Кого нашли — связываем, кого нет — заводим: вход закрыт, права не выдаются."""
    from staff.models import Employee

    django_user_model.objects.create_user(
        username="petrova", last_name="Петрова", first_name="Анна"
    )

    result = services.import_doctors(VM_USERS, only_with_visits=False)

    assert (result.updated, result.created) == (1, 2)
    sidorov = django_user_model.objects.get(last_name="Сидоров")
    assert sidorov.username == "sidorov" and not sidorov.is_active  # уволенный
    assert not sidorov.has_usable_password() and not sidorov.groups.exists()
    assert Employee.objects.get(user=sidorov).position.name == "Ассистент"


def test_doctors_without_visits_are_skipped(db, monkeypatch) -> None:
    """Переносим только тех, у кого есть приёмы: кассиры и администраторы не нужны."""
    monkeypatch.setattr(services, "_doctors_with_visits", lambda: {"3", "4"})

    plan = services.doctor_rows(VM_USERS)

    assert [row["name"] for row in plan] == ["Петрова Анна", "Сидоров Пётр"]


def test_login_does_not_repeat(db, django_user_model) -> None:
    django_user_model.objects.create_user(
        username="sidorov", last_name="Сидоров", first_name="Иван"
    )

    plan = services.doctor_rows(
        [{"id": 9, "last_name": "Сидоров", "first_name": "Пётр"}], only_with_visits=False
    )

    assert plan[0]["action"] == "create" and plan[0]["login"] == "sidorovp"


def test_visits_imported_with_doctor_purpose_and_text(visits) -> None:
    from medical.models import Visit

    first = Visit.objects.get(treatment_html__contains="Осмотр")

    assert visits.created == 2 and len(visits.errors) == 2  # нет питомца, нет даты
    assert visits.skipped == 1  # удалённую медкарту не переносим
    assert first.doctor.last_name == "Петрова" and first.purpose.name == "Хирургия"
    assert first.pet.name == "Барсик" and first.client.last_name == "Пушкин"
    assert str(timezone.localtime(first.date))[:16] == "2026-03-14 10:30"
    assert "<script>" not in first.treatment_html  # текст очищается


def test_unknown_doctor_goes_to_transfer_account(visits) -> None:
    from medical.models import Visit

    second = Visit.objects.get(treatment_html__contains="Повторный")

    # Врача нет даже в выгрузке — приём не теряется, его можно переназначить потом.
    assert second.doctor.last_name == services.TRANSFER_DOCTOR and not second.doctor.is_active


def test_visits_second_run_changes_nothing(visits) -> None:
    from medical.models import Visit

    again = services.import_visits(MEDICAL_CARDS, COMBO_ITEMS)

    assert again.created == 0 and again.skipped == 3 and Visit.objects.count() == 2


# --- Повторный перенос и устойчивость к обрывам ---------------------------------------


def test_second_run_updates_clients_and_pets(people) -> None:
    """Клиника продолжает работать в VetManager: повторный перенос подтягивает изменения."""
    from clients.models import Client, Pet

    changed_client = [
        {
            **CLIENTS[0],
            "cell_phone": "700777888",
            "discount": "10.0000000000",
            "note": "сменил телефон",
        }
    ]
    changed_pet = [{**PETS[0], "alias": "Барсик Второй", "chip_number": "999111"}]

    clients_result = services.import_clients(changed_client)
    pets_result = services.import_pets(changed_pet)

    pushkin = Client.objects.get(journal_number="А-12")
    assert (clients_result.created, clients_result.updated) == (0, 1)
    assert pushkin.discount_percent == D("10.00") and pushkin.description == "сменил телефон"
    assert [p.number for p in pushkin.phones.all()] == ["+996700777888", "+996312900900"]
    assert (pets_result.created, pets_result.updated) == (0, 1)
    assert Pet.objects.get(chip_number="999111").name == "Барсик Второй"
    assert Client.objects.count() == 2 and Pet.objects.count() == 4  # ничего не задвоилось


def test_deleted_card_is_not_created_again(people) -> None:
    """Карточку удалили у нас — повторный перенос не заводит её заново."""
    from clients.models import Pet

    Pet.objects.get(name="Барсик").delete()

    result = services.import_pets(PETS)

    assert result.created == 0  # заново не завели
    assert Pet.objects.filter(name="Барсик").count() == 0  # осталась удалённой


def test_network_hiccup_is_retried(monkeypatch) -> None:
    """Разовая заминка в сети не обрывает перенос: пробуем ещё раз."""
    import json
    import urllib.error

    calls = {"n": 0}

    class FakeResponse:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *args):  # type: ignore[no-untyped-def]
            return False

        def read(self):  # type: ignore[no-untyped-def]
            payload = {
                "success": True,
                "data": {"totalCount": 1, "unit": [{"id": "1", "title": "шт"}]},
            }
            return json.dumps(payload).encode()

    def flaky(request, timeout=None):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("Temporary failure in name resolution")
        return FakeResponse()

    monkeypatch.setattr(client, "RETRY_PAUSE", 0)
    monkeypatch.setattr(client.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(client.settings, "VETMANAGER_URL", "https://clinic.vetmanager.cloud")
    monkeypatch.setattr(client.settings, "VETMANAGER_API_KEY", "key")

    assert client.fetch("Unit") == [{"id": "1", "title": "шт"}]
    assert calls["n"] == 2  # первая попытка сорвалась, вторая прошла


def test_no_connection_says_what_to_check(monkeypatch, settings) -> None:
    import urllib.error

    settings.VETMANAGER_URL = "https://clinic.vetmanager.cloud"
    settings.VETMANAGER_API_KEY = "key"
    monkeypatch.setattr(client, "RETRY_PAUSE", 0)
    monkeypatch.setattr(
        client.urllib.request,
        "urlopen",
        lambda *a, **kw: (_ for _ in ()).throw(urllib.error.URLError("name resolution")),
    )

    with pytest.raises(client.VetManagerError, match="Проверьте интернет на сервере"):
        client.fetch("Unit")


def test_visits_are_imported_in_batches(visits, monkeypatch) -> None:
    """Приёмы переносятся порциями: обрыв посреди не отменяет уже перенесённое."""
    from medical.models import Visit

    monkeypatch.setattr(services, "VISITS_BATCH", 1)
    Visit.objects.all().delete()
    services.Imported.objects.filter(kind="visit").delete()
    broken = [
        *MEDICAL_CARDS[:1],
        {
            "id": 704,
            "patient_id": 200,
            "user_id": 3,
            "admission_date": "2026-05-01 10:00:00",
            "description": "Вторая порция",
        },
    ]

    services.import_visits(broken, COMBO_ITEMS)

    assert Visit.objects.count() == 2


VM_STREETS = [{"id": 55, "title": "Жантошева", "type_title": "улица"}]


def test_address_and_phone_are_complete(db, monkeypatch) -> None:
    """Улица лежит отдельным справочником VetManager, код страны — отдельным полем."""
    from clients.models import Client

    monkeypatch.setattr(services, "_vetmanager_streets", lambda: {"55": VM_STREETS[0]})

    services.import_clients(CLIENTS)

    pushkin = Client.objects.get(journal_number="А-12")
    assert pushkin.city.name == "Бишкек" and pushkin.street.name == "улица Жантошева"
    assert pushkin.house == "70 кв. 12"
    # Код страны в выгрузке пуст — подставляем код клиники, а не оставляем «555098765».
    assert [p.number for p in pushkin.phones.all()] == ["+996555098765", "+996312900900"]


def test_phone_formats(db) -> None:
    assert services._phone_number("555287246", "") == "+996555287246"
    assert services._phone_number("0555287246", "") == "+996555287246"
    assert services._phone_number("+996555287246", "") == "+996555287246"
    assert services._phone_number("555287246", "996") == "+996555287246"
    assert services._phone_number("(703) 840-008", "") == "+996703840008"
    assert services._phone_number("", "") == ""


def test_city_and_street_come_as_nested_records(db, monkeypatch) -> None:
    """Так отвечает настоящий VetManager: city пусто, город и улица — в city_data
    и street_data, тип улицы — английским словом."""
    from clients.models import Client

    monkeypatch.setattr(services, "_vetmanager_streets", lambda: {})
    row = {
        "id": 2122,
        "last_name": "Burcin",
        "first_name": "Catak",
        "cell_phone": "555287246",
        "address": "",
        "apartment": "дом 30 кв",
        "city": "",
        "city_id": 252,
        "street_id": 124,
        "city_data": {"id": 252, "title": "Бишкек", "type_id": 1},
        "street_data": {"id": 124, "title": "Джал", "city_id": 252, "type": "microdistrict"},
        "status": "ACTIVE",
    }

    services.import_clients([row])

    found = Client.objects.get(last_name="Burcin")
    assert found.city.name == "Бишкек" and found.street.name == "микрорайон Джал"
    assert found.house == "дом 30 кв"

    # Повторный перенос не плодит города и улицы.
    services.import_clients([row])
    assert found.city.streets.count() == 1


def test_city_is_taken_from_street_directory(db, monkeypatch) -> None:
    """В списке клиентов вложенных записей может не быть — город берём у улицы из справочника."""
    from clients.models import Client

    street = {"id": 124, "title": "Джал", "type": "microdistrict", "city": {"title": "Бишкек"}}
    monkeypatch.setattr(services, "_vetmanager_streets", lambda: {"124": street})

    services.import_clients(
        [{"id": 7, "last_name": "Иванов", "city": "", "city_id": 252, "street_id": 124}]
    )

    found = Client.objects.get(last_name="Иванов")
    assert found.city.name == "Бишкек" and found.street.name == "микрорайон Джал"


def test_client_contract_mark_and_default_type(db, monkeypatch) -> None:
    """has_contract=1 → договор «б/н» (один, даже при повторном переносе); тип — «Обычный»."""
    from clients.models import Client

    monkeypatch.setattr(services, "_vetmanager_streets", lambda: {})
    rows = [
        {
            "id": 1,
            "last_name": "С договором",
            "has_contract": 1,
            "date_register": "2026-08-16 09:37:39",
        },
        {"id": 2, "last_name": "Без договора", "has_contract": 0},
    ]

    services.import_clients(rows)
    services.import_clients(rows)

    with_contract = Client.objects.get(last_name="С договором")
    assert [(c.number, str(c.date)) for c in with_contract.contracts.all()] == [
        ("б/н", "2026-08-16")
    ]
    assert not Client.objects.get(last_name="Без договора").contracts.exists()
    assert with_contract.client_type.name == "Обычный"


def test_doctor_contacts_are_imported(db) -> None:
    """Телефон и почта врача переносятся; телефон — с кодом страны."""
    from staff.models import Employee

    services.import_doctors(VM_USERS, only_with_visits=False)

    petrova = get_user_model().objects.get(last_name="Петрова")
    sidorov = get_user_model().objects.get(last_name="Сидоров")
    assert petrova.email == "petrova@clinic.kg"
    assert Employee.objects.get(user=petrova).phone == "+996555112233"
    assert Employee.objects.get(user=sidorov).phone == "+996700445566"
    assert sidorov.email == ""  # «не почта» — не адрес, не переносим


def test_existing_employee_contacts_are_not_overwritten(db, django_user_model) -> None:
    """У заведённого сотрудника свои контакты не затираются, пустые — заполняются."""
    from staff.models import Employee, Position

    user = django_user_model.objects.create_user(
        username="petrova", last_name="Петрова", first_name="Анна", email="my@clinic.kg"
    )
    position = Position.objects.first() or Position.objects.create(name="Врач")
    Employee.objects.update_or_create(user=user, defaults={"position": position})

    services.import_doctors(VM_USERS, only_with_visits=False)

    user.refresh_from_db()
    assert user.email == "my@clinic.kg"  # своё не трогаем
    assert Employee.objects.get(user=user).phone == "+996555112233"  # пустое заполнили


def test_rerun_fills_missing_contacts(db) -> None:
    """Повторный запуск шага дозаполняет контакты уже перенесённых врачей."""
    from staff.models import Employee

    without_contacts = [{"id": 3, "last_name": "Петрова", "first_name": "Анна", "is_active": 1}]
    services.import_doctors(without_contacts, only_with_visits=False)
    petrova = get_user_model().objects.get(last_name="Петрова")
    assert Employee.objects.get(user=petrova).phone == ""

    again = services.import_doctors(VM_USERS, only_with_visits=False)

    petrova.refresh_from_db()
    assert again.skipped == 1  # заново не заводим
    assert petrova.email == "petrova@clinic.kg"
    assert Employee.objects.get(user=petrova).phone == "+996555112233"


def test_sex_and_sterilization_are_split(people) -> None:
    """В VetManager пол и стерилизация в одном поле, у нас — пол и отдельный признак."""
    from clients.models import Pet

    chomar = Pet.objects.get(name="Чомар")
    musya = Pet.objects.get(name="Муся")
    barsik = Pet.objects.get(name="Барсик")

    assert (chomar.sex, chomar.sterilized) == (Pet.Sex.MALE, True)
    assert (musya.sex, musya.sterilized) == (Pet.Sex.FEMALE, True)
    assert (barsik.sex, barsik.sterilized) == (Pet.Sex.MALE, False)


def test_inactive_pet_keeps_status(people) -> None:
    """Неактивный в VetManager питомец не становится у нас активным."""
    from clients.models import Pet

    assert Pet.objects.get(name="Чомар").status == Pet.Status.INACTIVE
    assert Pet.objects.get(name="Барсик").status == Pet.Status.ACTIVE
    assert Pet.objects.get(name="Рекс").status == Pet.Status.DEAD


def test_medical_card_fields(visits) -> None:
    """Медкарта в VetManager — это MedicalCards: описание, рекомендации, диагноз, вес."""
    from medical.models import Visit

    card = Visit.objects.get(treatment_html__contains="Осмотр")

    assert card.purpose.name == "Хирургия" and card.result.name == "Выздоровление"
    assert card.weight == D("4.200") and card.temperature == D("38.9")
    assert "Повторно через 10 дней" in card.recommendations_html
    assert sorted(d.diagnosis.name for d in card.diagnoses.all()) == ["Абсцесс", "Отит наружный"]
    assert "<script>" not in card.treatment_html


def test_empty_diagnosis_is_not_created(visits) -> None:
    """«0» в поле диагноза — это пусто, а не диагноз с таким названием."""
    from medical.models import Visit

    assert Visit.objects.get(treatment_html__contains="Повторный").diagnoses.count() == 0


def test_diagnoses_handbook(db) -> None:
    """Справочник диагнозов VetManager переносится в наш, неактивные — неактивными."""
    from medical.models import Diagnosis

    result = services.import_diagnoses(VM_DIAGNOSES)

    # «Абсцесс» уже есть в нашем справочнике — связали, не задвоили.
    assert result.created + result.updated == 3
    assert Diagnosis.objects.get(name="Отит наружный").is_active
    assert not Diagnosis.objects.get(name="Старый диагноз").is_active  # неактивный в VetManager


def test_diagnosis_by_number_not_by_text(visits) -> None:
    """Диагноз берётся по номеру справочника: один и тот же диагноз не задваивается."""
    from medical.models import Diagnosis, Visit

    card = Visit.objects.get(treatment_html__contains="Осмотр")

    assert [d.diagnosis.pk for d in card.diagnoses.all()] == [
        Diagnosis.objects.get(name="Абсцесс").pk,
        Diagnosis.objects.get(name="Отит наружный").pk,
    ]
    assert Diagnosis.objects.filter(name__icontains="отит").count() == 1
