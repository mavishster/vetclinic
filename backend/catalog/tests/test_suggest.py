"""Подбор препаратов: опечатки, раскладка, аналоги по действующему веществу и группе."""

from decimal import Decimal

import pytest

from catalog import services
from catalog.models import DrugGroup, Item, ItemGroup, Kind, Substance, Unit

D = Decimal


def drug(name: str, substances: list[str] = (), groups: list[str] = ()) -> Item:
    item = services.save_item(
        Item(kind=Kind.GOODS, name=name, group=ItemGroup.objects.get(name="Препараты"), base_unit=Unit.objects.get(name="шт.")),
        [{"unit": Unit.objects.get(name="шт."), "price": D("100")}],
    )  # fmt: skip
    services.set_drug_info(
        item,
        [Substance.objects.get(name=s) for s in substances],
        [DrugGroup.objects.get(name=g) for g in groups] if groups else None,
    )
    return item


def names(text: str, section: str | None = None) -> list[str]:
    found = services.suggest(Item.objects.filter(is_active=True), text)
    return [f["item"].name for f in found if section is None or f["section"] == section]


@pytest.fixture
def drugs(db):
    return {
        "serenia": drug("Серения раствор 10 мг/мл", ["маропитант"]),
        "vomend": drug("Вомендин таблетки 16 мг", ["маропитант"]),
        "cerucal": drug("Церукал раствор", ["метоклопрамид"]),
        "ondan": drug("Ондансетрон 2 мг/мл", ["ондансетрон"]),
        "noshpa": drug("Но-шпа раствор", ["дротаверин"]),
        "gloves": drug("Перчатки смотровые"),
    }


def test_reference_is_seeded(db) -> None:
    assert DrugGroup.objects.filter(name="Противорвотные").exists()
    assert Substance.objects.get(name="маропитант").group.name == "Противорвотные"
    assert Substance.objects.get(name="метамизол натрия").synonyms == "анальгин"


def test_group_comes_from_substance(drugs) -> None:
    assert [g.name for g in drugs["serenia"].drug_groups.all()] == ["Противорвотные"]


def test_exact_and_typo(drugs) -> None:
    assert names("серения", "name") == ["Серения раствор 10 мг/мл"]
    assert "Церукал раствор" in names("церукл", "name")  # пропущена буква
    assert "Церукал раствор" in names("цирукал", "name")  # ошибка в букве
    assert "Ондансетрон 2 мг/мл" in names("ондансетрн", "name")


def test_wrong_keyboard_layout(drugs) -> None:
    assert "Церукал раствор" in names("wthernfk", "name")  # «церукал» латиницей


def test_analogues_by_substance(drugs) -> None:
    by_substance = names("серения", "substance")
    assert by_substance == ["Вомендин таблетки 16 мг"]  # тот же маропитант
    assert "Серения раствор 10 мг/мл" not in by_substance  # сам препарат — в разделе названий


def test_search_by_substance_name(drugs) -> None:
    found = services.suggest(Item.objects.filter(is_active=True), "маропитант")
    assert {f["item"].name for f in found} == {
        "Серения раствор 10 мг/мл",
        "Вомендин таблетки 16 мг",
    }
    assert {f["note"] for f in found} == {"маропитант"}


def test_search_by_group_name(drugs) -> None:
    assert set(names("противорвотное", "group")) >= {"Церукал раствор", "Ондансетрон 2 мг/мл"}
    assert "Но-шпа раствор" not in names("противорвотное")  # другая группа


def test_same_group_for_found_drug(drugs) -> None:
    sections = {
        f["item"].name: f["section"]
        for f in services.suggest(Item.objects.filter(is_active=True), "церукал")
    }
    assert sections["Церукал раствор"] == "name"
    assert sections["Ондансетрон 2 мг/мл"] == "group"  # другое противорвотное
    assert sections.get("Вомендин таблетки 16 мг") == "group"


def test_items_without_substances_are_found_by_name_only(drugs) -> None:
    assert names("перчатки") == ["Перчатки смотровые"]
    assert names("перчтки", "name") == ["Перчатки смотровые"]


def test_short_text_and_nothing_found(drugs) -> None:
    assert services.suggest(Item.objects.all(), "ц") == []
    assert names("ксяоплдж") == []
