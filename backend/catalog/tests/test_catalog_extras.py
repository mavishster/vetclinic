"""Доработки каталога: комбинации позиции, убранные единицы, фильтры учёта, защита справочников."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from catalog import services
from catalog.models import Item, ItemGroup, Kind, Unit

D = Decimal


@pytest.fixture
def api(db):
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    return client


@pytest.fixture
def drug(db):
    return services.save_item(
        Item(
            kind=Kind.GOODS,
            name="Мильбемакс",
            group=ItemGroup.objects.get(name="Препараты"),
            base_unit=Unit.objects.get(name="таб."),
        ),
        [
            {"unit": Unit.objects.get(name="таб."), "price": D("350")},
            {"unit": Unit.objects.get(name="упак."), "ratio": D("2"), "price": D("650")},
        ],
    )


def test_combinations_with_item_and_removed_units(api, drug) -> None:
    combo = services.save_combination(
        Item(name="Дегельминтизация", group=ItemGroup.objects.get(name="Процедуры и манипуляции")),
        [{"item_unit": drug.units.get(unit__name="таб.")}],
    )
    pack = drug.units.get(unit__name="упак.")
    services.save_item(
        drug,
        [
            {
                "id": drug.units.get(unit__name="таб.").pk,
                "unit": Unit.objects.get(name="таб."),
                "price": D("350"),
            }
        ],
    )

    combos = api.get(f"/api/catalog/items/{drug.pk}/combinations/").json()
    removed = api.get(f"/api/catalog/items/{drug.pk}/removed-units/").json()

    assert combos == [{"id": str(combo.pk), "name": "Дегельминтизация"}]
    assert [(r["unit_name"], r["price"]) for r in removed] == [("упак.", "650.00")]
    assert not drug.units.filter(pk=pack.pk).exists()


def test_tracked_and_not_for_sale_filters(api, drug) -> None:
    services.mark_stock_tracked(drug)
    hidden = services.save_item(
        Item(
            kind=Kind.GOODS,
            name="Шприц для клиники",
            group=ItemGroup.objects.get(name="Расходные материалы"),
            base_unit=Unit.objects.get(name="шт."),
            for_sale=False,
        ),
        [{"unit": Unit.objects.get(name="шт."), "price": D("10"), "for_sale": False}],
    )

    def names(query):
        return [i["name"] for i in api.get(f"/api/catalog/items/?{query}").json()["results"]]

    assert names("tracked=yes") == ["Мильбемакс"]
    assert names("tracked=no") == [hidden.name]
    assert names("not_for_sale=true") == [hidden.name]


def test_used_directory_cannot_be_deleted_only_deactivated(api, drug) -> None:
    group = ItemGroup.objects.get(name="Препараты")
    empty = ItemGroup.objects.get(name="Зоотовары")

    refused = api.delete(f"/api/catalog/groups/{group.pk}/")
    deactivated = api.patch(f"/api/catalog/groups/{group.pk}/", {"is_active": False}, format="json")
    deleted = api.delete(f"/api/catalog/groups/{empty.pk}/")

    assert refused.status_code == 400
    assert "используется в записях: 1" in refused.json()["non_field_errors"][0]
    assert deactivated.status_code == 200
    assert deleted.status_code == 204


def test_used_species_cannot_be_deleted(api, db) -> None:
    from clients import services as clients
    from clients.models import Breed, Client, Pet, Species

    cats = Species.objects.get(name="Кошки")
    clients.save_pet(
        Pet(
            owner=clients.save_client(Client(last_name="Иванова")),
            name="Барсик",
            species=cats,
            breed=Breed.objects.get(name="Метис", species=cats),
        )
    )

    assert api.delete(f"/api/clients/species/{cats.pk}/").status_code == 400


def test_base_unit_can_change_until_first_receipt_or_sale(drug) -> None:
    """Единица учёта исправляется, пока по товару нет количеств — даже если стоит отметка
    «ведётся складской учёт» (после переноса прайса она есть у всех товаров)."""
    from core import services as core
    from inventory import services as inventory
    from inventory.models import StockDocument, Warehouse

    services.mark_stock_tracked(drug)
    drug.base_unit = Unit.objects.get(name="фл.")
    services.save_item(drug, [{"unit": drug.base_unit, "price": Decimal("10")}])  # прихода не было

    receipt = inventory.save_document(
        StockDocument(kind="receipt", warehouse=Warehouse.objects.get(name="Основной склад")),
        [{"item_unit": drug.units.get(), "quantity": Decimal("5"), "price": Decimal("3")}],
    )
    drug.base_unit = Unit.objects.get(name="шт.")
    with pytest.raises(services.CatalogError, match="нельзя менять после первого прихода"):
        services.save_item(drug)  # есть складской документ, даже черновик

    receipt.delete()
    services.save_item(drug, [{"unit": drug.base_unit, "price": Decimal("10")}])  # убрали — можно
    core.execute_document(
        inventory.save_document(
            StockDocument(kind="receipt", warehouse=Warehouse.objects.get(name="Основной склад")),
            [{"item_unit": drug.units.get(), "quantity": Decimal("5"), "price": Decimal("3")}],
        )
    )
    drug.base_unit = Unit.objects.get(name="фл.")
    with pytest.raises(services.CatalogError, match="нельзя менять после первого прихода"):
        services.save_item(drug)


def test_list_ordering_by_columns(api, drug) -> None:
    service_group = ItemGroup.objects.filter(kind=Kind.SERVICE).first()
    services.save_item(
        Item(kind=Kind.SERVICE, name="анализ крови", group=service_group, article="A-1",
             base_unit=Unit.objects.get(name="усл.")),
        [{"unit": Unit.objects.get(name="усл."), "price": Decimal("900")}],
    )  # fmt: skip
    services.save_item(
        Item(
            kind=Kind.GOODS, name="Бинт", group=drug.group, base_unit=Unit.objects.get(name="шт.")
        ),
        [{"unit": Unit.objects.get(name="шт."), "price": Decimal("15")}],
    )

    def names(ordering: str) -> list[str]:
        rows = api.get(f"/api/catalog/items/?ordering={ordering}").json()["results"]
        return [r["name"] for r in rows]

    by_price = names("price")
    assert names("name")[0] == "анализ крови" and names("-name")[-1] == "анализ крови"
    assert by_price.index("Бинт") < by_price.index("анализ крови")
    assert names("-price").index("анализ крови") < names("-price").index("Бинт")
    assert names("unit")[-1] == "анализ крови"  # у услуги единицы нет — в конце
    assert names("article")[0] == "анализ крови"  # пустые артикулы — в конце
    groups = [
        r["group_name"] for r in api.get("/api/catalog/items/?ordering=group").json()["results"]
    ]
    assert groups == sorted(groups, key=str.lower)
    assert len(names("wrong")) == 3  # неизвестная колонка — порядок по умолчанию
