"""Порядок в прайсе: объединение фасовок и дублей, перенесённых из VetManager."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from vetmanager import tidy
from vetmanager.models import Imported

D = Decimal


def goods(name: str, unit: str, price: str) -> Item:
    unit_row = Unit.objects.filter(name=unit).first() or Unit.objects.create(name=unit)
    return catalog.save_item(
        Item(
            kind=Kind.GOODS,
            name=name,
            group=ItemGroup.objects.filter(kind=Kind.GOODS).first(),
            base_unit=unit_row,
        ),
        [
            {
                "unit": unit_row.pk,
                "ratio": D("1"),
                "pricing": "fixed",
                "price": D(price),
                "for_sale": True,
            }
        ],
    )


@pytest.fixture
def aktiflora(db):
    return [
        goods("АКТИФЛОРА синбиотик для кошек (1 саше)", "саше", "60"),
        goods("АКТИФЛОРА синбиотик для кошек (уп 30 саше)", "упак.", "1700"),
    ]


def test_finds_packs_and_quantity_from_name(aktiflora) -> None:
    found = tidy.suggestions()

    assert len(found) == 1 and found[0]["kind"] == "packs"
    assert found[0]["name"] == "АКТИФЛОРА синбиотик для кошек"
    # Количество взято из названия, единица — своя у позиции: саше и упаковка.
    assert [(row["quantity"], row["unit"]) for row in found[0]["items"]] == [
        ("1", "саше"),
        ("30", "упак."),
    ]


def test_merge_makes_one_item_with_two_units(aktiflora) -> None:
    found = tidy.suggestions()[0]

    item = tidy.merge(
        found["name"],
        [
            {"item": row["id"], "quantity": row["quantity"], "unit": row["unit"]}
            for row in found["items"]
        ],
    )

    assert Item.objects.filter(name__startswith="АКТИФЛОРА").count() == 1
    assert item.name == "АКТИФЛОРА синбиотик для кошек" and item.base_unit.name == "саше"
    units = {u.unit.name: (u.ratio, u.price) for u in item.units.all()}
    assert units["саше"] == (D("1.000000"), D("60.00"))
    assert units["упак."] == (D("30.000000"), D("1700.00"))  # 1 упак. = 30 саше


def test_duplicates_are_merged_into_one(db) -> None:
    goods("Корм Hills 2 кг", "шт.", "3000")
    goods("Корм Hills 2 кг ", "шт.", "3000")

    found = tidy.suggestions()

    assert found[0]["kind"] == "duplicates"
    item = tidy.merge(
        found[0]["name"],
        [{"item": row["id"], "quantity": "1", "unit": "шт."} for row in found[0]["items"]],
    )
    assert (
        Item.objects.filter(name__startswith="Корм Hills").count() == 1 and item.units.count() == 1
    )


def test_different_dose_is_not_merged(db) -> None:
    goods("Цефтриаксон 0,5 г фл.", "фл.", "100")
    goods("Цефтриаксон 1 г фл.", "фл.", "150")

    assert tidy.suggestions() == []  # разные дозировки — разные товары


def test_used_item_is_not_merged(aktiflora, django_user_model) -> None:
    from billing import services as billing
    from billing.models import Invoice
    from clients import services as clients
    from clients.models import Client

    owner = clients.save_client(Client(last_name="Петров"))
    billing.save_invoice(Invoice(client=owner), [{"item_unit": aktiflora[0].units.get()}])
    found = tidy.suggestions()[0]

    assert found["items"][0]["used"] is True
    with pytest.raises(catalog.CatalogError, match="Уже используются"):
        tidy.merge(
            found["name"],
            [
                {"item": row["id"], "quantity": row["quantity"], "unit": row["unit"]}
                for row in found["items"]
            ],
        )


def test_api_needs_right(aktiflora, django_user_model) -> None:
    admin = APIClient()
    admin.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    plain = APIClient()
    plain.force_authenticate(django_user_model.objects.create_user(username="u", password="x"))

    assert len(admin.get("/api/vetmanager/tidy/").json()) == 1
    assert plain.get("/api/vetmanager/tidy/").status_code == 403


def test_weight_in_name_is_not_a_pack(db) -> None:
    """«Корм Hills 2 кг» — это вес товара, а не упаковка из двух штук."""
    goods("Корм Hills 2 кг", "шт.", "3000")
    goods("Корм Hills 2 кг ", "шт.", "3000")

    found = tidy.suggestions()[0]

    # Это две одинаковые записи одного товара: вес остаётся в названии после объединения.
    assert found["kind"] == "duplicates"
    assert [row["quantity"] for row in found["items"]] == ["2", "2"]


def test_documents_count_is_shown_and_sorts(db, monkeypatch) -> None:
    """Сверху — то, что чаще встречается в счетах: с этого и начинают разбор."""
    rare = goods("Редкий корм (1 саше)", "саше", "60")
    rare_pack = goods("Редкий корм (уп 30 саше)", "упак.", "1500")
    often = goods("Ходовой корм (1 саше)", "саше", "70")
    often_pack = goods("Ходовой корм (уп 30 саше)", "упак.", "1800")
    for item, external_id in ((rare, "1"), (rare_pack, "2"), (often, "3"), (often_pack, "4")):
        Imported.objects.create(kind="item", external_id=external_id, target_id=item.pk)
    monkeypatch.setattr(
        tidy.client,
        "fetch",
        lambda model, *a, **kw: (
            [{"good_id": 3}] * 40 + [{"good_id": 4}] * 10 + [{"good_id": 1}] * 2
        ),
    )

    found = tidy.suggestions()

    assert [row["name"] for row in found[:2]] == ["Ходовой корм", "Редкий корм"]
    assert found[0]["documents"] == 50 and found[1]["documents"] == 2
    assert [part["documents"] for part in found[0]["items"]] == [40, 10]


def test_documents_are_optional(aktiflora, monkeypatch) -> None:
    """Связи с VetManager нет — экран всё равно работает, просто без чисел."""
    monkeypatch.setattr(
        tidy.client,
        "fetch",
        lambda *a, **kw: (_ for _ in ()).throw(tidy.client.VetManagerError("нет связи")),
    )

    found = tidy.suggestions()

    assert found and found[0]["documents"] == 0


# --- Фасовки препаратов: приход упаковками, отпуск поштучно ----------------------------


def test_packaging_finds_pack_only_drugs(db) -> None:
    """Остаток в упаковках, а отпускают поштучно — такую позицию надо поправить."""
    goods("Ношпа уп. 8 табл.", "упак.", "160")
    goods("Цефтриаксон фл. 1 г", "фл.", "120")
    goods("Корм Hills 2 кг", "шт.", "3000")  # учёт в штуках — всё в порядке

    rows = {row["name"]: row for row in tidy.packaging_rows(with_documents=False)}

    assert set(rows) == {"Ношпа уп. 8 табл.", "Цефтриаксон фл. 1 г"}
    assert (rows["Ношпа уп. 8 табл."]["quantity"], rows["Ношпа уп. 8 табл."]["inside"]) == (
        "8",
        "таб.",
    )


def test_packaging_switches_to_pieces(db) -> None:
    """После правки остаток ведётся в таблетках, упаковка — единица закупки."""
    item = goods("Ношпа уп. 8 табл.", "упак.", "160")

    tidy.set_packaging(str(item.pk), D("8"), "таб.", D("25"))

    item.refresh_from_db()
    units = {u.unit.name: (u.ratio, u.price, u.for_purchase) for u in item.units.all()}
    assert item.base_unit.name == "таб."
    assert units["таб."] == (D("1.000000"), D("25.00"), False)
    assert units["упак."] == (D("8.000000"), D("160.00"), True)  # приход упаковками


def test_packaging_skips_items_with_piece_unit(db) -> None:
    """Если поштучная единица уже заведена внутри позиции, трогать нечего."""
    unit = Unit.objects.get(name="мл")
    pack = Unit.objects.get(name="фл.")
    catalog.save_item(
        Item(
            kind=Kind.GOODS,
            name="Веткокцин фл. 100 мл",
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
            },
            {
                "unit": pack.pk,
                "ratio": D("100"),
                "pricing": "fixed",
                "price": D("1500"),
                "for_sale": True,
            },
        ],
    )

    assert tidy.packaging_rows(with_documents=False) == []


def test_packaging_refuses_used_item(db) -> None:
    """Позицию с приходами и продажами не трогаем — единицу учёта менять поздно."""
    from billing import services as billing
    from billing.models import Invoice
    from clients import services as clients
    from clients.models import Client

    item = goods("Ношпа уп. 8 табл.", "упак.", "160")
    owner = clients.save_client(Client(last_name="Петров"))
    billing.save_invoice(Invoice(client=owner), [{"item_unit": item.units.get()}])

    with pytest.raises(catalog.CatalogError, match="уже используется"):
        tidy.set_packaging(str(item.pk), D("8"), "таб.", D("25"))


def test_sets_and_pieces_are_not_listed(db) -> None:
    """Наборы и саше продаются целиком — делить их не нужно."""
    goods("Набор для приёма", "набор", "150")
    goods("АКТИФЛОРА (1 саше)", "саше", "60")
    goods("Ношпа уп. 8 табл.", "упак.", "160")

    names = {row["name"] for row in tidy.packaging_rows(with_documents=False)}

    assert names == {"Ношпа уп. 8 табл."}


def test_marked_ok_disappears_from_list(db) -> None:
    """«Не трогать»: позиция уходит из списка и не возвращается."""
    item = goods("Гептрал 1фл", "фл.", "600")
    assert tidy.packaging_rows(with_documents=False)

    tidy.skip_packaging(str(item.pk))

    assert tidy.packaging_rows(with_documents=False) == []


def test_sizes_are_not_packs(db) -> None:
    """«Воротник №5» и «№8» — размеры, а не фасовки одного товара."""
    goods("Воротник №5", "шт.", "450")
    goods("Воротник №8", "шт.", "250")

    assert tidy.suggestions(with_documents=False) == []


def test_skip_pair_removes_group(db) -> None:
    """«Не объединять»: пара уходит из списка насовсем."""
    goods("Шампунь (1 фл.)", "фл.", "300")
    goods("Шампунь (уп 6 фл.)", "упак.", "1600")
    found = tidy.suggestions(with_documents=False)
    assert found

    tidy.skip_pair(found[0]["base_name"])

    assert tidy.suggestions(with_documents=False) == []


def test_two_pack_sizes_get_own_units(db) -> None:
    """Упаковки по 2 и по 6 таблеток — каждая своей единицей, не затирают друг друга."""
    one = goods("Успокоин (1 таблетка)", "таб.", "150")
    two = goods("Успокоин (2 таблетки)", "упак.", "450")
    six = goods("Успокоин (6таблеток)", "упак.", "850")

    item = tidy.merge(
        "Успокоин",
        [
            {"item": str(one.pk), "quantity": "1", "unit": "таб."},
            {"item": str(two.pk), "quantity": "2", "unit": "упак."},
            {"item": str(six.pk), "quantity": "6", "unit": "упак."},
        ],
    )

    units = {u.unit.name: (u.ratio, u.price) for u in item.units.all()}
    assert units["таб."] == (D("1.000000"), D("150.00"))
    assert units["упак."] == (D("2.000000"), D("450.00"))
    assert units["упак. 6 таб."] == (D("6.000000"), D("850.00"))


def test_volume_in_name_pairs_bottle_and_ml(db) -> None:
    """«Supramil …, 10 мл.» (флакон) и «… 1 мл.» (отлив) — один препарат в двух фасовках."""
    goods("Supramil эмульсия для собак от 25 кг до 50, 10 мл.", "фл.", "1200")
    goods("Supramil эмульсия для собак от 25 кг до 50, 1мл.", "мл", "120")

    found = tidy.suggestions(with_documents=False)

    assert len(found) == 1
    assert found[0]["name"] == "Supramil эмульсия для собак от 25 кг до 50"
    assert [(p["quantity"], p["unit"]) for p in found[0]["items"]] == [("1", "мл"), ("10", "фл.")]


def test_same_unit_different_dose_is_not_a_pair(db) -> None:
    """«Цефтриаксон 0,5 г» и «1 г» — разные дозировки, объединять нельзя."""
    goods("Цефтриаксон 0,5 г", "фл.", "100")
    goods("Цефтриаксон 1 г", "фл.", "150")

    assert tidy.suggestions(with_documents=False) == []


def test_merged_bottle_and_ml(db) -> None:
    """Флакон и отлив становятся одной позицией: остаток в мл, флакон = 10 мл."""
    goods("Supramil для собак, 10 мл.", "фл.", "1200")
    goods("Supramil для собак, 1мл.", "мл", "120")
    found = tidy.suggestions(with_documents=False)[0]

    item = tidy.merge(
        found["name"],
        [{"item": p["id"], "quantity": p["quantity"], "unit": p["unit"]} for p in found["items"]],
    )

    units = {u.unit.name: (u.ratio, u.price) for u in item.units.all()}
    assert item.base_unit.name == "мл"
    assert units["мл"] == (D("1.000000"), D("120.00"))
    assert units["фл."] == (D("10.000000"), D("1200.00"))
    assert Item.objects.filter(name__startswith="Supramil").count() == 1
