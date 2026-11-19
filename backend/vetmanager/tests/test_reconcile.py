"""Сверка переноса: сколько в VetManager, сколько у нас, чего не хватает."""

from decimal import Decimal

import pytest

from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from vetmanager import client, reconcile
from vetmanager.models import Imported

D = Decimal


def goods(name: str) -> Item:
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
                "price": D("100"),
                "for_sale": True,
            }
        ],
    )


@pytest.mark.django_db
def test_items_section_counts_both_sides(monkeypatch) -> None:
    """Перенеслась одна позиция из двух — вторую называем поимённо."""
    item = goods("Цефтриаксон")
    Imported.objects.create(kind="item", external_id="1", target_id=item.pk)
    monkeypatch.setattr(
        client,
        "fetch",
        lambda *a, **kw: [{"id": 1, "title": "Цефтриаксон"}, {"id": 2, "title": "Анальгин"}],
    )

    section = reconcile.items_section()

    assert (section["theirs"], section["ours"]) == (2, 1)
    assert [row["name"] for row in section["missing"]] == ["Анальгин"]


@pytest.mark.django_db
def test_deleted_item_is_not_counted_as_ours(monkeypatch) -> None:
    """Позиция удалена у нас — связь есть, но считать её перенесённой нельзя."""
    item = goods("Физраствор 100мл")
    Imported.objects.create(kind="item", external_id="3", target_id=item.pk)
    catalog.delete_item(item)
    monkeypatch.setattr(client, "fetch", lambda *a, **kw: [{"id": 3, "title": "Физраствор 100мл"}])

    section = reconcile.items_section()

    assert (section["theirs"], section["ours"]) == (1, 0)


@pytest.mark.django_db
def test_invoice_lines_count_what_would_be_lost(monkeypatch) -> None:
    """По строкам счетов видно, сколько именно потеряется, а не только сколько позиций."""
    item = goods("Цефтриаксон")
    Imported.objects.create(kind="item", external_id="1", target_id=item.pk)

    def fetch(model, *args, **kwargs):
        if model == "invoiceDocument":
            return [{"good_id": 1}] * 5 + [{"good_id": 2}] * 20 + [{"good_id": 9}] * 3
        return [{"id": 1, "title": "Цефтриаксон"}, {"id": 2, "title": "Анальгин"}]

    monkeypatch.setattr(client, "fetch", fetch)

    section = reconcile.invoice_lines_section()

    assert (section["theirs"], section["ours"]) == (28, 5)
    assert section["missing"][0] == {
        "id": "2",
        "name": "Анальгин",
        "lines": 20,
        "reason": "позиция не перенеслась",
    }
    assert section["missing"][1]["reason"] == "позиция удалена в самом VetManager"


@pytest.mark.django_db
def test_report_marks_sections(monkeypatch) -> None:
    monkeypatch.setattr(client, "fetch", lambda *a, **kw: [])

    found = {row["key"]: row for row in reconcile.report()}

    assert found["clients"]["ok"] is True  # ноль там, ноль здесь — сошлось
    assert set(found) == {"items", "clients", "pets", "visits", "invoices", "invoice_lines"}


@pytest.mark.django_db
def test_no_connection_is_shown(monkeypatch) -> None:
    def broken(*args, **kwargs):
        raise client.VetManagerError("нет связи")

    monkeypatch.setattr(client, "fetch", broken)

    found = reconcile.report()

    assert all(row.get("error") for row in found)
