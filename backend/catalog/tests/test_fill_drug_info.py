"""Подстановка действующего вещества и группы по названию позиции."""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from catalog import services
from catalog.models import Item, ItemGroup, Kind, Substance, Unit

D = Decimal


def drug(name: str) -> Item:
    unit = Unit.objects.get(name="мл")
    return services.save_item(
        Item(
            kind=Kind.GOODS,
            name=name,
            group=ItemGroup.objects.filter(kind=Kind.GOODS).first(),
            base_unit=unit,
        ),
        [
            {
                "unit": unit.pk,
                "ratio": D("1"),
                "pricing": "fixed",
                "price": D("100"),
                "for_sale": True,
            }
        ],
    )


@pytest.mark.django_db
def test_dry_run_changes_nothing() -> None:
    item = drug("Цефтриаксон фл. 1 г")

    out = StringIO()
    call_command("fill_drug_info", stdout=out)

    assert "цефтриаксон" in out.getvalue().lower()
    assert not item.substances.exists()  # без --apply ничего не записано


@pytest.mark.django_db
def test_apply_sets_substance_and_group() -> None:
    """Вещество берётся из названия, группа подставляется по веществу."""
    item = drug("Цефтриаксон фл. 1 г")

    call_command("fill_drug_info", "--apply", stdout=StringIO())

    item.refresh_from_db()
    assert [s.name.lower() for s in item.substances.all()] == ["цефтриаксон"]
    assert item.drug_groups.exists()  # группа подставилась сама


@pytest.mark.django_db
def test_brand_names_are_known() -> None:
    """Торговые названия тоже распознаются — и кириллицей, и латиницей."""
    heptral = drug("Гептрал 1фл")
    supramil = drug("Supramil эмульсия для собак, 10 мл.")

    call_command("fill_drug_info", "--apply", stdout=StringIO())

    assert [s.name.lower() for s in heptral.substances.all()] == ["адеметионин"]
    assert supramil.substances.exists()


@pytest.mark.django_db
def test_filled_items_are_not_touched() -> None:
    """Уже заполненные позиции не трогаем: врач мог проставить своё."""
    item = drug("Цефтриаксон фл. 1 г")
    other = Substance.objects.exclude(name__iexact="цефтриаксон").first()
    services.set_drug_info(item, [other], None)

    call_command("fill_drug_info", "--apply", stdout=StringIO())

    assert [s.name for s in item.substances.all()] == [other.name]


@pytest.mark.django_db
def test_missing_substance_is_created() -> None:
    """Вещества нет в справочнике — заводим его: иначе препарат не связать."""
    item = drug("Апомед 16 мг уп. 10 табл.")

    call_command("fill_drug_info", "--apply", stdout=StringIO())

    assert [s.name.lower() for s in item.substances.all()] == ["апоморфин"]


@pytest.mark.django_db
def test_vaccines_get_group_without_substance() -> None:
    """У вакцин действующего вещества нет — ставим только группу."""
    item = drug("Вакцина Нобивак DHPPI")

    call_command("fill_drug_info", "--apply", stdout=StringIO())

    assert not item.substances.exists()
    assert [g.name for g in item.drug_groups.all()] == ["Вакцины"]


@pytest.mark.django_db
def test_consumables_are_not_drugs() -> None:
    """Воротники, катетеры и шампуни — не препараты: вещество им не ставим."""
    collar = drug("Воротник №5")
    catheter = drug("Катетер уретральный для кошек")

    out = StringIO()
    call_command("fill_drug_info", "--apply", stdout=out)

    assert "не препаратов: 2" in out.getvalue()
    assert not collar.substances.exists() and not catheter.substances.exists()


@pytest.mark.django_db
def test_second_pass_brands() -> None:
    """Второй проход по прайсу: Клавуксицин, Марбобел, Нольпаза и другие."""
    rows = {
        "Клавуксицин® таблетки 250мг": "амоксициллин",
        "Марбобел 10% , 1 мл": "марбофлоксацин",
        "Нольпаза 40 мг": "пантопразол",
        "Рикарфа 20мг 1 табл.": "карпрофен",
        "Милпразон д/кошек от 2кг": "празиквантел",
    }
    items = {name: drug(name) for name in rows}

    call_command("fill_drug_info", "--apply", stdout=StringIO())

    for name, substance in rows.items():
        assert [s.name.lower() for s in items[name].substances.all()] == [substance], name


@pytest.mark.django_db
def test_third_pass_brands() -> None:
    """Третий проход: Симпарика, Фенпраз, Ципровет, Флексопрофен и другие."""
    rows = {
        "Симпарика 40мг д/собак 10-20 кг 1шт": "сароланер",
        "Фенпраз сусп. д/кошек 5мл": "празиквантел",
        "Ципровет д/собак 1табл.": "ципрофлоксацин",
        "Флексопрофен 5% 50мл": "кетопрофен",
        "Соладокси 100 мг для кошек и собак": "доксициклин",
        "Фебтал для собак и кошек": "фенбендазол",
    }
    items = {name: drug(name) for name in rows}

    call_command("fill_drug_info", "--apply", stdout=StringIO())

    for name, substance in rows.items():
        assert [s.name.lower() for s in items[name].substances.all()] == [substance], name
