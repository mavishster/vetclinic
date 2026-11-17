"""fix_packaging: упаковка препаратов по правилам клиники."""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from vetmanager import tidy
from vetmanager.management.commands.audit_drugs import audit

D = Decimal
pytestmark = pytest.mark.django_db


def unit(name: str) -> Unit:
    return Unit.objects.filter(name=name).first() or Unit.objects.create(name=name)


def pack_item(name: str, base: str = "упак.", group: str = "Препараты", price: str = "150") -> Item:
    row, _ = ItemGroup.objects.get_or_create(name=group, kind=Kind.GOODS)
    return catalog.save_item(
        Item(kind=Kind.GOODS, name=name, group=row, base_unit=unit(base)),
        [{"unit": unit(base).pk, "ratio": D("1"), "pricing": "fixed", "price": D(price),
          "for_sale": True}],
    )  # fmt: skip


def run(*args: str) -> str:
    out = StringIO()
    call_command("fix_packaging", *args, stdout=out)
    return out.getvalue()


def flagged() -> set[str]:
    return {item.name for item, _ in audit()["no_retail"]}


def test_preview_changes_nothing() -> None:
    item = pack_item("Зоокард д/кошек уп. 10 табл.")

    text = run()

    assert "Завести розничную единицу: 1" in text and "цена за таб.: 15.00" in text
    item.refresh_from_db()
    assert item.base_unit.name == "упак."


def test_tablets_get_retail_unit_and_pack_for_purchase() -> None:
    item = pack_item("Зоокард д/кошек уп. 10 табл.")

    run("--apply")

    item.refresh_from_db()
    units = {u.unit.name: u for u in item.units.all()}
    assert item.base_unit.name == "таб."
    assert units["упак."].ratio == D("10") and units["упак."].for_purchase
    assert units["таб."].price == D("15.00") and units["таб."].for_sale


def test_injection_by_ml_and_suspension_whole() -> None:
    pack_item("Новокаин 2% фл.20мл МАГ", "фл.", price="200")
    pack_item("Зоокард сусп. д/кошек фл. 25мл", "фл.")

    run("--apply")

    assert Item.objects.get(name__startswith="Новокаин").base_unit.name == "мл"
    assert Item.objects.get(name__startswith="Зоокард").base_unit.name == "фл."
    assert flagged() == set()  # суспензия помечена «не трогать»


def test_zootovary_vaccines_and_single_piece_are_left_whole() -> None:
    pack_item("Шампунь DOCTOR VIC 250мл", "фл.", group="Зоотовары")
    pack_item("Вакцина Нобивак DHPPI", "фл.")
    pack_item("Симпарика 10мг д/собак 2,5-5 кг 1шт")

    text = run("--apply")

    assert "помечено «не трогать»: 3" in text and flagged() == set()


def test_unclear_names_are_only_listed() -> None:
    item = pack_item("Цефтриаксон", "фл.")
    pack_item("Амикацин р/р 500мг:2мл №10")

    text = run("--apply")

    assert "Разобрать вручную: 2" in text
    item.refresh_from_db()
    assert item.base_unit.name == "фл." and "Цефтриаксон" in flagged()


def test_item_with_quantities_is_reported_not_changed(monkeypatch) -> None:
    item = pack_item("Зоокард д/кошек уп. 10 табл.")
    monkeypatch.setattr(tidy, "_quantity_usage", lambda _item: ["счета"])

    text = run("--apply")

    item.refresh_from_db()
    assert item.base_unit.name == "упак." and "не удалось" in text
