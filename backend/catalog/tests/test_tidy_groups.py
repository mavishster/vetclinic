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
        "УЗИ брюшной полости": "Визуальная диагностика",
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


@pytest.mark.django_db
def test_lab_services_are_not_dumped_into_other() -> None:
    """Лабораторные исследования — своя группа, а не «Прочее»."""
    rows = {
        "Akso FeLV/FIV Real-time PCR Kit Лейкоз кошек": "Лабораторные исследования",
        "Общий анализ крови": "Лабораторные исследования",
        "Бак посев с подтитровкой": "Лабораторные исследования",
        "УЗИ брюшной полости": "Визуальная диагностика",
        "Рентген в двух проекциях": "Визуальная диагностика",
    }
    items = {name: item(name, Kind.SERVICE) for name in rows}

    call_command("tidy_groups", "--apply", stdout=StringIO())

    for name, group in rows.items():
        items[name].refresh_from_db()
        assert items[name].group.name == group, name


@pytest.mark.django_db
def test_unknown_service_keeps_its_group() -> None:
    """Непонятную услугу не перекладываем: лучше оставить, чем свалить в «Прочее»."""
    own = ItemGroup.objects.create(name="Особые услуги", kind=Kind.SERVICE)
    service = item("Литичка (кошка)", Kind.SERVICE)
    service.group = own
    service.save(update_fields=["group"])

    call_command("tidy_groups", "--apply", stdout=StringIO())

    service.refresh_from_db()
    assert service.group.name == "Особые услуги"


@pytest.mark.django_db
def test_common_service_groups_and_other_listing() -> None:
    rows = {
        "Вакцинация Нобивак Tricat": "Вакцинация и профилактика",
        "Эвтаназия (кошка)": "Эвтаназия и кремация",
        "Удаление зуба": "Стоматология",
        "Кесарево сечение": "Акушерство и гинекология",
        "Передержка в стационаре": "Стационар",
        "Определение породы": "",  # «роды» внутри «породы» не должны попасть в акушерство
    }
    other = ItemGroup.objects.create(name="Прочее", kind=Kind.SERVICE)
    items = {name: item(name, Kind.SERVICE) for name in rows}
    for service in items.values():
        service.group = other
        service.save(update_fields=["group"])
    out = StringIO()

    call_command("tidy_groups", "--other", stdout=out)
    call_command("tidy_groups", "--apply", stdout=StringIO())

    assert "не удалось разложить: 1" in out.getvalue() and "Определение породы" in out.getvalue()
    for name, group in rows.items():
        items[name].refresh_from_db()
        assert items[name].group.name == (group or "Прочее"), name
