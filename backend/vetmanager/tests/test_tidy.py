"""Порядок в прайсе: объединение фасовок и дублей, перенесённых из VetManager."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from vetmanager import tidy

D = Decimal


def goods(name: str, unit: str, price: str) -> Item:
    unit_row = Unit.objects.filter(name=unit).first() or Unit.objects.create(name=unit)
    return catalog.save_item(
        Item(
            kind=Kind.GOODS,
            name=name,
            group=ItemGroup.objects.filter(kind=Kind.GOODS).first(),
            base_unit=unit_row,
        ),
        [
            {
                "unit": unit_row.pk,
                "ratio": D("1"),
                "pricing": "fixed",
                "price": D(price),
                "for_sale": True,
            }
        ],
    )


@pytest.fixture
def aktiflora(db):
    return [
        goods("АКТИФЛОРА синбиотик для кошек (1 саше)", "саше", "60"),
        goods("АКТИФЛОРА синбиотик для кошек (уп 30 саше)", "упак.", "1700"),
    ]


def test_finds_packs_and_quantity_from_name(aktiflora) -> None:
    found = tidy.suggestions()

    assert len(found) == 1 and found[0]["kind"] == "packs"
    assert found[0]["name"] == "АКТИФЛОРА синбиотик для кошек"
    # Количество взято из названия, единица — своя у позиции: саше и упаковка.
    assert [(row["quantity"], row["unit"]) for row in found[0]["items"]] == [
        ("1", "саше"),
        ("30", "упак."),
    ]


def test_merge_makes_one_item_with_two_units(aktiflora) -> None:
    found = tidy.suggestions()[0]

    item = tidy.merge(
        found["name"],
        [
            {"item": row["id"], "quantity": row["quantity"], "unit": row["unit"]}
            for row in found["items"]
        ],
    )

    assert Item.objects.filter(name__startswith="АКТИФЛОРА").count() == 1
    assert item.name == "АКТИФЛОРА синбиотик для кошек" and item.base_unit.name == "саше"
    units = {u.unit.name: (u.ratio, u.price) for u in item.units.all()}
    assert units["саше"] == (D("1.000000"), D("60.00"))
    assert units["упак."] == (D("30.000000"), D("1700.00"))  # 1 упак. = 30 саше


def test_duplicates_are_merged_into_one(db) -> None:
    goods("Корм Hills 2 кг", "шт.", "3000")
    goods("Корм Hills 2 кг ", "шт.", "3000")

    found = tidy.suggestions()

    assert found[0]["kind"] == "duplicates"
    item = tidy.merge(
        found[0]["name"],
        [{"item": row["id"], "quantity": "1", "unit": "шт."} for row in found[0]["items"]],
    )
    assert (
        Item.objects.filter(name__startswith="Корм Hills").count() == 1 and item.units.count() == 1
    )


def test_different_dose_is_not_merged(db) -> None:
    goods("Цефтриаксон 0,5 г фл.", "фл.", "100")
    goods("Цефтриаксон 1 г фл.", "фл.", "150")

    assert tidy.suggestions() == []  # разные дозировки — разные товары


def test_used_item_is_not_merged(aktiflora, django_user_model) -> None:
    from billing import services as billing
    from billing.models import Invoice
    from clients import services as clients
    from clients.models import Client

    owner = clients.save_client(Client(last_name="Петров"))
    billing.save_invoice(Invoice(client=owner), [{"item_unit": aktiflora[0].units.get()}])
    found = tidy.suggestions()[0]

    assert found["items"][0]["used"] is True
    with pytest.raises(catalog.CatalogError, match="Уже используются"):
        tidy.merge(
            found["name"],
            [
                {"item": row["id"], "quantity": row["quantity"], "unit": row["unit"]}
                for row in found["items"]
            ],
        )


def test_api_needs_right(aktiflora, django_user_model) -> None:
    admin = APIClient()
    admin.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    plain = APIClient()
    plain.force_authenticate(django_user_model.objects.create_user(username="u", password="x"))

    assert len(admin.get("/api/vetmanager/tidy/").json()) == 1
    assert plain.get("/api/vetmanager/tidy/").status_code == 403


def test_weight_in_name_is_not_a_pack(db) -> None:
    """«Корм Hills 2 кг» — это вес товара, а не упаковка из двух штук."""
    goods("Корм Hills 2 кг", "шт.", "3000")
    goods("Корм Hills 2 кг ", "шт.", "3000")

    found = tidy.suggestions()[0]

    assert found["name"] == "Корм Hills 2 кг" and found["kind"] == "duplicates"
    assert [row["quantity"] for row in found["items"]] == [None, None]
