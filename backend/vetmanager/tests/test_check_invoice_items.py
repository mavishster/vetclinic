"""Проверка позиций из счетов VetManager перед переносом счетов."""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from vetmanager import client, tidy
from vetmanager.models import Imported

D = Decimal


def goods(name: str, price: str = "100") -> Item:
    unit = Unit.objects.get(name="мл")
    return catalog.save_item(
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
                "price": D(price),
                "for_sale": True,
            }
        ],
    )


@pytest.mark.django_db
def test_reports_everything_is_ready(monkeypatch) -> None:
    item = goods("Цефтриаксон")
    Imported.objects.create(kind="item", external_id="77", target_id=item.pk)
    monkeypatch.setattr(client, "fetch", lambda *a, **kw: [{"good_id": 77}] * 3)

    out = StringIO()
    call_command("check_invoice_items", stdout=out)

    assert "Всё на месте" in out.getvalue()


@pytest.mark.django_db
def test_reports_missing_item(monkeypatch) -> None:
    """Позиция из счетов к нам не переносилась — скажем об этом до переноса счетов."""
    monkeypatch.setattr(client, "fetch", lambda *a, **kw: [{"good_id": 999}] * 5)

    out = StringIO()
    call_command("check_invoice_items", stdout=out)

    assert "не переносились: 1" in out.getvalue()


@pytest.mark.django_db
def test_merge_keeps_link_to_surviving_item(monkeypatch) -> None:
    """После объединения строки счетов находят оставшуюся позицию, а не удалённую."""
    small = goods("Ациломаг 1 мл", "50")
    big = goods("Ациломаг 100 мл", "1300")
    Imported.objects.create(kind="item", external_id="11", target_id=small.pk)
    Imported.objects.create(kind="item", external_id="12", target_id=big.pk)

    merged = tidy.merge(
        "Ациломаг",
        [
            {"item": str(small.pk), "quantity": "1", "unit": "мл"},
            {"item": str(big.pk), "quantity": "100", "unit": "фл."},
        ],
    )

    targets = set(Imported.objects.filter(kind="item").values_list("target_id", flat=True))
    assert targets == {merged.pk}
    monkeypatch.setattr(client, "fetch", lambda *a, **kw: [{"good_id": 11}, {"good_id": 12}])
    out = StringIO()
    call_command("check_invoice_items", stdout=out)
    assert "Всё на месте" in out.getvalue()


@pytest.mark.django_db
def test_repair_relinks_merged_items(monkeypatch) -> None:
    """Связь с удалённой позиции переводится на живую — по названию из VetManager."""
    merged = goods("Ациломаг")
    gone = goods("Ациломаг 100 мл (МАГ)")
    Imported.objects.create(kind="item", external_id="12", target_id=gone.pk)
    catalog.delete_item(gone)
    monkeypatch.setattr(
        client, "fetch", lambda *a, **kw: [{"id": 12, "title": "Ациломаг 100 мл (МАГ)"}]
    )

    call_command("repair_item_links", "--apply", stdout=StringIO())

    link = Imported.objects.get(kind="item", external_id="12")
    assert str(link.target_id) == str(merged.pk)


@pytest.mark.django_db
def test_repair_dry_run_changes_nothing(monkeypatch) -> None:
    merged = goods("Ациломаг")
    gone = goods("Ациломаг 100 мл (МАГ)")
    Imported.objects.create(kind="item", external_id="12", target_id=gone.pk)
    catalog.delete_item(gone)
    monkeypatch.setattr(
        client, "fetch", lambda *a, **kw: [{"id": 12, "title": "Ациломаг 100 мл (МАГ)"}]
    )

    out = StringIO()
    call_command("repair_item_links", stdout=out)

    assert str(Imported.objects.get(external_id="12").target_id) == str(gone.pk)
    assert merged.name in out.getvalue()


@pytest.mark.django_db
def test_missing_items_show_names(monkeypatch) -> None:
    """У позиций, которых у нас нет, видно название — или что их нет и в VetManager."""
    monkeypatch.setattr(
        client,
        "fetch",
        lambda model, *a, **kw: (
            [{"good_id": 999}] * 4
            if model == "invoiceDocument"
            else [{"id": 999, "title": "Интубация"}]
        ),
    )

    out = StringIO()
    call_command("check_invoice_items", stdout=out)

    assert "Интубация" in out.getvalue()


@pytest.mark.django_db
def test_repair_matches_despite_different_wording(monkeypatch) -> None:
    """«Физраствор 100мл» и наш «Физраствор фл. 100мл» — одна позиция."""
    ours = goods("Физраствор фл. 100мл")
    gone = goods("Физраствор 100мл")
    Imported.objects.create(kind="item", external_id="3", target_id=gone.pk)
    catalog.delete_item(gone)
    monkeypatch.setattr(client, "fetch", lambda *a, **kw: [{"id": 3, "title": "Физраствор 100мл"}])

    call_command("repair_item_links", "--apply", stdout=StringIO())

    assert str(Imported.objects.get(external_id="3").target_id) == str(ours.pk)


@pytest.mark.django_db
def test_repair_skips_when_several_fit(monkeypatch) -> None:
    """Подходят две позиции — не выбираем наугад, оставляем человеку."""
    goods("Веткокцин 5% 10 мл")
    goods("Веткокцин 5% 100 мл")
    gone = goods("Веткокцин 5% 1 мл")
    Imported.objects.create(kind="item", external_id="4", target_id=gone.pk)
    catalog.delete_item(gone)
    monkeypatch.setattr(client, "fetch", lambda *a, **kw: [{"id": 4, "title": "Веткокцин 5% 1 мл"}])

    out = StringIO()
    call_command("repair_item_links", "--apply", stdout=out)

    assert str(Imported.objects.get(external_id="4").target_id) == str(gone.pk)
    assert "не нашли пару: 1" in out.getvalue()


@pytest.mark.django_db
def test_repair_keeps_dosage_apart(monkeypatch) -> None:
    """«Вазосан 2,5мг» и «Вазосан 5мг» — разные препараты, связывать их нельзя."""
    goods("Вазосан 5мг уп. 30 табл.")
    gone = goods("Вазосан 2,5мг 1 табл")
    Imported.objects.create(kind="item", external_id="7", target_id=gone.pk)
    catalog.delete_item(gone)
    monkeypatch.setattr(
        client, "fetch", lambda *a, **kw: [{"id": 7, "title": "Вазосан 2,5мг 1 табл"}]
    )

    out = StringIO()
    call_command("repair_item_links", "--apply", stdout=out)

    assert str(Imported.objects.get(external_id="7").target_id) == str(gone.pk)
    assert "не нашли пару: 1" in out.getvalue()


@pytest.mark.django_db
def test_repair_matches_same_dosage(monkeypatch) -> None:
    """А та же дозировка в другой фасовке — одна позиция."""
    ours = goods("Авекардит 1,25мг для мелких собак")
    gone = goods("Авекардит 1,25мг для мелких собак уп. 28 табл.")
    Imported.objects.create(kind="item", external_id="8", target_id=gone.pk)
    catalog.delete_item(gone)
    monkeypatch.setattr(
        client,
        "fetch",
        lambda *a, **kw: [{"id": 8, "title": "Авекардит 1,25мг для мелких собак уп. 28 табл."}],
    )

    call_command("repair_item_links", "--apply", stdout=StringIO())

    assert str(Imported.objects.get(external_id="8").target_id) == str(ours.pk)
