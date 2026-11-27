"""Несколько штрихкодов у одной упаковки (ADR-025): один код — одна упаковка."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit

D = Decimal


def goods(name, pack_barcode="", extra=None):
    return catalog.save_item(
        Item(
            kind=Kind.GOODS,
            name=name,
            group=ItemGroup.objects.get(name="Препараты"),
            base_unit=Unit.objects.get(name="таб."),
        ),
        [
            {"unit": Unit.objects.get(name="таб."), "price": D("90")},
            {
                "unit": Unit.objects.get(name="упак."),
                "ratio": D("10"),
                "price": D("800"),
                "barcode": pack_barcode,
                "extra_barcodes": extra or [],
            },
        ],
    )


@pytest.fixture
def sinulox(db):
    return goods("Синулокс 50 мг", "5414736043517", ["4600000000017"])


def test_extra_barcode_finds_the_same_pack(sinulox) -> None:
    pack = sinulox.units.get(unit__name="упак.")

    assert catalog.find_by_barcode("5414736043517") == pack
    assert catalog.find_by_barcode("4600000000017") == pack
    assert list(catalog.search_items(Item.objects.all(), "4600000000017")) == [sinulox]


def test_barcode_of_another_item_is_refused(sinulox) -> None:
    with pytest.raises(catalog.CatalogError, match="уже записан у «Синулокс 50 мг"):
        goods("Другой препарат", extra=["4600000000017"])
    with pytest.raises(catalog.CatalogError, match="уже записан"):
        goods("Ещё один", pack_barcode="5414736043517")


def test_extra_barcodes_are_replaced_on_save(sinulox) -> None:
    pack = sinulox.units.get(unit__name="упак.")
    units = [
        {"id": u.pk, "unit": u.unit, "ratio": u.ratio, "price": u.price}
        for u in sinulox.units.all()
    ]
    next(u for u in units if u["id"] == pack.pk)["extra_barcodes"] = ["4600000000024"]

    catalog.save_item(sinulox, units)

    assert [b.code for b in pack.extra_barcodes.all()] == ["4600000000024"]
    assert catalog.find_by_barcode("4600000000017") is None
    goods("Теперь можно", extra=["4600000000017"])  # освободившийся код — свободен


def test_main_barcode_cannot_repeat_as_extra(db) -> None:
    with pytest.raises(catalog.CatalogError, match="уже указан как основной"):
        goods("Синулокс", "5414736043517", ["5414736043517"])


def test_add_barcode_main_first_then_extra(db) -> None:
    item = goods("Синулокс 50 мг")
    pack = item.units.get(unit__name="упак.")

    catalog.add_barcode(pack, "5414736043517")
    catalog.add_barcode(pack, "4600000000017")
    catalog.add_barcode(pack, "4600000000017")  # повтор — ничего не меняет

    pack.refresh_from_db()
    assert pack.barcode == "5414736043517"
    assert [b.code for b in pack.extra_barcodes.all()] == ["4600000000017"]


def test_item_api_shows_and_saves_extra_barcodes(sinulox) -> None:
    api = APIClient()
    api.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))

    item = api.get(f"/api/catalog/items/{sinulox.pk}/").json()
    pack = next(u for u in item["units"] if u["barcode"] == "5414736043517")
    assert pack["extra_barcodes"] == ["4600000000017"]

    pack["extra_barcodes"] = ["4600000000017", "4600000000024"]
    saved = api.patch(f"/api/catalog/items/{sinulox.pk}/", {"units": item["units"]}, format="json")

    assert saved.status_code == 200, saved.json()
    assert catalog.find_by_barcode("4600000000024") == sinulox.units.get(unit__name="упак.")


def test_assign_internal_barcodes_and_filter(sinulox) -> None:
    api = APIClient()
    api.force_authenticate(get_user_model().objects.create_superuser(username="b", password="x"))
    bare = goods("Без кода")
    pack, tablet = bare.units.get(unit__name="упак."), bare.units.get(unit__name="таб.")

    listed = api.get("/api/catalog/items/", {"no_barcode": "true"}).json()["results"]
    assert [row["name"] for row in listed] == ["Без кода"]  # у Синулокса коды есть

    own = sinulox.units.get(unit__name="упак.")
    result = api.post(
        "/api/catalog/items/assign-barcodes/", {"units": [str(pack.pk), str(own.pk)]}, format="json"
    ).json()

    pack.refresh_from_db()
    assert result["assigned"] == 1
    assert pack.barcode.startswith("20") and len(pack.barcode) == 13
    assert catalog.find_by_barcode(pack.barcode) == pack
    assert own.barcode == "5414736043517"  # свой код не меняется
    assert tablet.barcode == ""  # таблетке не отмечали — без кода
    assert api.get("/api/catalog/items/", {"no_barcode": "true"}).json()["results"] == []
