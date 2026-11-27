"""Объединение позиций (ADR-026): единицы основной позиции и дублей."""

from decimal import Decimal

from catalog import services as catalog
from catalog.models import Item, ItemGroup, ItemUnit, Kind, Unit

D = Decimal


def test_merge_when_units_trade_places(db) -> None:
    """Единица основной позиции становится другой, а её место занимает единица дубля.
    Единицы сохранялись по одной (по возрастанию количества), и база на миг видела две
    одинаковые единицы у одной позиции — IntegrityError, ошибка 500."""
    group = ItemGroup.objects.get(name="Препараты")
    upak = Unit.objects.get(name="упак.")
    box, block = Unit.objects.create(name="коробка"), Unit.objects.create(name="блок")
    main = catalog.save_item(
        Item(kind=Kind.GOODS, name="Основная", group=group, base_unit=upak),
        [{"unit": upak, "price": D("100")}, {"unit": box, "ratio": D("10"), "price": D("900")}],
    )
    dup = catalog.save_item(
        Item(kind=Kind.GOODS, name="Дубль", group=group, base_unit=box),
        [{"unit": box, "price": D("950")}],
    )
    main_pack, main_box = main.units.get(unit=upak), main.units.get(unit=box)

    catalog.merge_items(
        main.pk, [main.pk, dup.pk], "Основная", upak.pk,
        [
            {"item_unit": main_pack.pk, "unit": upak.pk, "ratio": D("1")},
            {"item_unit": main_box.pk, "unit": block.pk, "ratio": D("10")},  # «коробка» → «блок»
            {"item_unit": dup.units.get().pk, "unit": box.pk, "ratio": D("20")},  # дубль → «коробка»
        ],
        dry_run=False,
    )  # fmt: skip

    assert sorted((u.unit.name, u.ratio) for u in ItemUnit.objects.filter(item=main)) == [
        ("блок", D("10")), ("коробка", D("20")), ("упак.", D("1")),
    ]  # fmt: skip
