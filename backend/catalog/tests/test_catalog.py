"""Каталог: цены и наценки, правила карточки, поиск, история цен."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from catalog import services
from catalog.models import Item, ItemGroup, ItemUnit, Kind, Unit
from catalog.services import CatalogError
from core.context import acting_user

D = Decimal


def unit(name: str) -> Unit:
    return Unit.objects.get(name=name)


def group(name: str) -> ItemGroup:
    return ItemGroup.objects.get(name=name)


def make_goods(name="Витамины 8в1", units=None, group_name="Препараты", **fields) -> Item:
    item = Item(
        kind=Kind.GOODS, name=name, group=group(group_name), base_unit=unit("таб."), **fields
    )
    return services.save_item(
        item,
        units
        if units is not None
        else [
            {"unit": unit("упак."), "ratio": D("216"), "pricing": "fixed", "price": D("600")},
            {"unit": unit("таб."), "ratio": D("1"), "pricing": "fixed", "price": D("3")},
        ],
    )


@pytest.mark.parametrize(
    ("value", "step", "expected"),
    [
        (D("2.777"), D("0.01"), D("2.78")),
        (D("2.5"), D("1"), D("3.00")),
        (D("1347.83"), D("10"), D("1350.00")),
    ],
)
def test_round_price(value, step, expected) -> None:
    assert services.round_price(value, step) == expected


@pytest.mark.django_db
def test_fixed_price_and_floating_range() -> None:
    item = make_goods(
        units=[
            {"unit": unit("таб."), "ratio": D("1"), "price": D("600"),
             "price_min": D("450"), "price_max": D("750")},
        ]
    )  # fmt: skip
    pack = item.units.get()

    assert services.price_of(pack) == D("600")
    assert services.is_price_allowed(pack, D("500"))
    assert not services.is_price_allowed(pack, D("800"))


@pytest.mark.django_db
def test_markup_own_or_from_group_and_zero_is_real_zero() -> None:
    item = make_goods(
        group_name="Корма",  # наценка группы 25 %
        units=[
            {"unit": unit("упак."), "ratio": D("10"), "pricing": "markup", "markup_percent": None},
            {"unit": unit("таб."), "ratio": D("1"), "pricing": "markup", "markup_percent": D("0")},
            {"unit": unit("шт."), "ratio": D("2"), "pricing": "markup", "markup_percent": D("100")},
        ],
    )
    pack, tablet, piece = (item.units.get(unit__name=n) for n in ("упак.", "таб.", "шт."))

    assert services.effective_markup(pack) == D("25")
    assert services.price_of(pack, cost_per_base=D("10")) == D("125.00")
    assert services.price_of(tablet, cost_per_base=D("10")) == D("10.00")
    assert services.price_of(piece, cost_per_base=D("10")) == D("40.00")  # 2 таб. × 10 × 2


@pytest.mark.django_db
def test_markup_uses_manual_cost_and_rounding_or_unknown() -> None:
    item = make_goods(
        units=[{"unit": unit("таб."), "ratio": D("1"), "pricing": "markup", "markup_percent": D("33"),
                "rounding": D("10")}],
    )  # fmt: skip
    pack = item.units.get()

    assert services.price_of(pack) is None  # ни партии, ни себестоимости
    item.manual_cost = D("1013.40")
    item.save()
    pack.refresh_from_db()
    assert services.price_of(pack) == D("1350.00")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("units", "message"),
    [
        ([{"unit": "упак.", "ratio": D("0"), "price": D("1")}], "больше нуля"),
        ([{"unit": "таб.", "ratio": D("1")}], "укажите цену"),
        ([{"unit": "таб.", "ratio": D("1"), "price": D("5"), "price_min": D("10")}], "вне диапазона"),
        ([{"unit": "таб.", "ratio": D("1"), "price": D("5"), "price_min": D("9"), "price_max": D("8")}],
         "минимальная цена больше"),
        ([{"unit": "упак.", "ratio": D("3"), "price": D("1")}, {"unit": "упак.", "ratio": D("2"),
          "price": D("2")}], "«упак.» указана в двух строках"),
        ([{"unit": "таб.", "ratio": D("5"), "price": D("1")}], "всегда равна 1 таб."),
        ([{"unit": "таб.", "ratio": D("1"), "price": D("1"), "for_sale": False}], "хотя бы одну"),
    ],
)  # fmt: skip
def test_unit_rules(units, message) -> None:
    prepared = [{**u, "unit": unit(u["unit"])} for u in units]

    with pytest.raises(CatalogError, match=message):
        make_goods(units=prepared)


@pytest.mark.django_db
def test_group_must_match_kind_and_name_required() -> None:
    with pytest.raises(CatalogError, match="Группа не подходит"):
        make_goods(group_name="Хирургия")
    with pytest.raises(CatalogError, match="название"):
        make_goods(name="  ")


@pytest.mark.django_db
def test_service_price_is_always_fixed_per_one() -> None:
    service = Item(kind=Kind.SERVICE, name="Первичный приём", group=group("Приём и консультации"),
                   base_unit=unit("усл."))  # fmt: skip

    services.save_item(
        service, [{"unit": unit("усл."), "ratio": D("5"), "pricing": "markup", "price": D("900")}]
    )

    stored = service.units.get()
    assert (stored.ratio, stored.pricing, stored.price) == (D("1"), "fixed", D("900"))


@pytest.mark.django_db
def test_saving_units_updates_existing_and_removes_missing() -> None:
    item = make_goods()
    pack = item.units.get(unit__name="упак.")

    services.save_item(
        item, [{"id": pack.pk, "unit": unit("упак."), "ratio": D("216"), "price": D("650")}]
    )

    assert list(item.units.values_list("unit__name", "price")) == [("упак.", D("650.00"))]
    assert ItemUnit.all_objects.filter(item=item, is_deleted=True).count() == 1
    assert item.units.get().pk == pack.pk  # та же запись — история цены сохраняется


@pytest.mark.django_db
def test_search_by_words_article_and_barcode() -> None:
    item = make_goods(name="Витамины 8в1 для собак", article="VT-216")
    ItemUnit.objects.filter(item=item, unit__name="упак.").update(barcode="4601234567890")

    def found(text):
        return list(services.search_items(Item.objects.all(), text))

    assert found("витамины собак") == [item]
    assert found("vt-216") == [item]
    assert found("4601234567890") == [item]
    assert found("кошек") == []


@pytest.mark.django_db
def test_price_history_shows_only_price_changes_with_author() -> None:
    user = get_user_model().objects.create_user(
        username="manager", password="x", last_name="Орлова"
    )
    with acting_user(user):
        item = make_goods(units=[{"unit": unit("таб."), "ratio": D("1"), "price": D("600")}])
        pack = item.units.get()
        pack.barcode = "123"  # не цена — в историю цен не попадает
        pack.save()
        services.save_item(
            item, [{"id": pack.pk, "unit": unit("таб."), "ratio": D("1"), "price": D("650")}]
        )

    history = services.price_history(item)

    assert [h["price"] for h in history] == ["650.00", "600.00"]
    assert history[0]["user"] == "Орлова"


def test_non_base_unit_equal_to_base_is_rejected(db) -> None:
    from decimal import Decimal

    from catalog import services
    from catalog.models import Item, ItemGroup, Kind, Unit

    with pytest.raises(services.CatalogError, match="не может быть равна 1 упак."):
        services.save_item(
            Item(kind=Kind.GOODS, name="Тразапентин", group=ItemGroup.objects.get(name="Препараты"), base_unit=Unit.objects.get(name="упак.")),
            [{"unit": Unit.objects.get(name="упак."), "price": Decimal("600")},
             {"unit": Unit.objects.get(name="таб."), "ratio": Decimal("1"), "price": Decimal("100")}],
        )  # fmt: skip
    item = services.save_item(
        Item(kind=Kind.GOODS, name="Тразапентин", group=ItemGroup.objects.get(name="Препараты"), base_unit=Unit.objects.get(name="упак.")),
        [{"unit": Unit.objects.get(name="упак."), "price": Decimal("600")},
         {"unit": Unit.objects.get(name="таб."), "ratio": Decimal("0.125"), "price": Decimal("100")}],
    )  # fmt: skip
    assert item.units.get(unit__name="таб.").ratio == Decimal("0.125")  # доля упаковки — можно
