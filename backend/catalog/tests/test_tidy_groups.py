"""Разбор групп прайса: товары и услуги со своими разделами."""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from catalog import services
from catalog.models import Item, ItemGroup, Kind, Unit

D = Decimal


def item(name: str, kind: str = Kind.GOODS) -> Item:
    unit = Unit.objects.get(name="мл" if kind == Kind.GOODS else "усл.")
    group = ItemGroup.objects.filter(kind=kind).first()
    return services.save_item(
        Item(kind=kind, name=name, group=group, base_unit=unit),
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
def test_goods_are_sorted_by_name() -> None:
    """Группа — это «с какой полки»: лечебный шампунь всё равно уход, а не препарат."""
    rows = {
        "Шампунь с хлоргексидином 150мл": "Зоотовары",
        "Воротник №8": "Зоотовары",
        "Шприцы 5 мл": "Медматериалы",
        "Экспресс-тест на панлейкопению": "Лабораторные",
        "Корм Hills почечный 2 кг": "Корма",
        "Цефтриаксон 1 г": "Препараты",
    }
    items = {name: item(name) for name in rows}

    call_command("tidy_groups", "--apply", stdout=StringIO())

    for name, group in rows.items():
        items[name].refresh_from_db()
        assert items[name].group.name == group, name
        assert items[name].group.kind == Kind.GOODS


@pytest.mark.django_db
def test_services_are_sorted_by_name() -> None:
    rows = {
        "Первичный приём": "Приём и консультации",
        "Вызов на дом": "Приём и консультации",
        "УЗИ брюшной полости": "Диагностика",
        "Кастрация кота": "Хирургия и анестезия",
        "Стационар сутки": "Стационар",
        "Стрижка когтей": "Груминг",
    }
    items = {name: item(name, Kind.SERVICE) for name in rows}

    call_command("tidy_groups", "--apply", stdout=StringIO())

    for name, group in rows.items():
        items[name].refresh_from_db()
        assert items[name].group.name == group, name
        assert items[name].group.kind == Kind.SERVICE


@pytest.mark.django_db
def test_empty_groups_are_removed() -> None:
    ItemGroup.objects.create(name="Вызов", kind=Kind.GOODS)

    call_command("tidy_groups", "--apply", stdout=StringIO())

    assert not ItemGroup.objects.filter(name="Вызов").exists()


@pytest.mark.django_db
def test_dry_run_changes_nothing() -> None:
    shampoo = item("Шампунь с хлоргексидином 150мл")
    was = shampoo.group.name

    out = StringIO()
    call_command("tidy_groups", stdout=out)

    shampoo.refresh_from_db()
    assert shampoo.group.name == was
    assert "Зоотовары" in out.getvalue()
