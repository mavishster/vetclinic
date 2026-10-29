"""Комбинации: состав, цены (своя или по прайсу), правила."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from catalog import services
from catalog.models import Item, ItemGroup, Kind, Unit
from catalog.services import CatalogError

D = Decimal


@pytest.fixture
def parts(db):
    visit = services.save_item(
        Item(kind=Kind.SERVICE, name="Приём", group=ItemGroup.objects.get(name="Приём и консультации"),
             base_unit=Unit.objects.get(name="усл.")),
        [{"unit": Unit.objects.get(name="усл."), "price": D("500")}],
    )  # fmt: skip
    vaccine = services.save_item(
        Item(kind=Kind.GOODS, name="Нобивак", group=ItemGroup.objects.get(name="Вакцины"),
             base_unit=Unit.objects.get(name="доза")),
        [{"unit": Unit.objects.get(name="доза"), "price": D("900")}],
    )  # fmt: skip
    return visit.units.get(), vaccine.units.get()


def make_combo(lines, name="Вакцинация", **fields):
    combo = Item(name=name, group=ItemGroup.objects.get(name="Вакцинация"), **fields)
    return services.save_combination(combo, lines)


def test_price_is_sum_of_current_prices(parts) -> None:
    visit, vaccine = parts
    combo = make_combo([{"item_unit": visit}, {"item_unit": vaccine, "quantity": D("2")}])

    assert combo.kind == Kind.COMBO
    assert services.combination_price(combo) == D("2300.00")


def test_own_price_is_fixed_and_reset_returns_to_price_list(parts) -> None:
    visit, vaccine = parts
    combo = make_combo([
        {"item_unit": visit, "price_override": D("0")},
        {"item_unit": vaccine, "price_override": D("800")},
    ])  # fmt: skip
    vaccine.price = D("1000")
    vaccine.save()

    assert services.combination_price(combo) == D("800.00")
    services.reset_combination_prices(combo)
    assert services.combination_price(combo) == D("1500.00")


def test_expand_gives_lines_for_invoice(parts) -> None:
    visit, vaccine = parts
    combo = make_combo([{"item_unit": visit}, {"item_unit": vaccine}], is_template=True)

    lines = services.expand_combination(combo)

    assert [(line["item_unit"].item.name, line["total"]) for line in lines] == [
        ("Приём", D("500.00")),
        ("Нобивак", D("900.00")),
    ]


def test_rules(parts) -> None:
    visit, _ = parts
    combo = make_combo([{"item_unit": visit}])

    with pytest.raises(CatalogError, match="хотя бы одну"):
        make_combo([], name="Пустая")
    with pytest.raises(CatalogError, match="больше нуля"):
        make_combo([{"item_unit": visit, "quantity": D("0")}], name="Ноль")
    nested_unit = services.save_item(
        Item(kind=Kind.GOODS, name="X", group=ItemGroup.objects.get(name="Препараты"),
             base_unit=Unit.objects.get(name="шт.")),
        [{"unit": Unit.objects.get(name="шт."), "price": D("1")}],
    ).units.get()  # fmt: skip
    nested_unit.item = combo  # подменяем: позиция из комбинации
    with pytest.raises(CatalogError, match="вложить"):
        make_combo([{"item_unit": nested_unit}], name="Вложенная")


def test_combo_group_must_be_service_group(parts) -> None:
    visit, _ = parts
    combo = Item(name="Не та группа", group=ItemGroup.objects.get(name="Препараты"))

    with pytest.raises(CatalogError, match="Группа"):
        services.save_combination(combo, [{"item_unit": visit}])


def test_api_create_list_and_reset(parts, django_user_model) -> None:
    visit, vaccine = parts
    api = APIClient()
    api.force_authenticate(django_user_model.objects.create_superuser(username="a", password="x"))
    group = str(ItemGroup.objects.get(name="Вакцинация").pk)

    created = api.post(
        "/api/catalog/items/",
        {"kind": "combo", "name": "Вакцинация DHPPi", "group": group, "print_mode": "name",
         "lines": [{"item_unit": str(visit.pk), "price_override": "0"},
                   {"item_unit": str(vaccine.pk), "quantity": "1"}]},
        format="json",
    )  # fmt: skip
    combo_id = created.json()["id"]
    reset = api.post(f"/api/catalog/items/{combo_id}/reset-prices/")
    combos = api.get("/api/catalog/items/?kind=combo").json()["results"]

    assert created.status_code == 201
    assert created.json()["combo_price"] == "900.00"
    assert created.json()["lines"][0]["current_price"] == "500.00"
    assert reset.json()["combo_price"] == "1400.00"
    assert [c["name"] for c in combos] == ["Вакцинация DHPPi"]
