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
