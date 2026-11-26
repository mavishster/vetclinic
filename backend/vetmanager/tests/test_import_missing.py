"""Перенос недостающих позиций прайса с причинами отказов."""

from io import StringIO

import pytest
from django.core.management import call_command

from catalog import services as catalog
from catalog.models import Item, Kind
from vetmanager import client
from vetmanager.models import Imported

VM_GOODS = [
    {
        "id": 38,
        "title": "Вакдерм",
        "is_active": 1,
        "is_for_sale": 1,
        "group": {"id": 74, "title": "Вакцинации", "is_service": 1},
        "goodSaleParams": [{"price": "500", "coefficient": "1", "is_last": 1, "status": "active"}],
    },
    {
        "id": 164,
        "title": "Вакдерм-F уп.10 доз",
        "is_active": 1,
        "is_for_sale": 1,
        "is_warehouse_account": 1,
        "unitStorage": {"id": 8, "title": "упаковка"},
        "group": {"id": 45, "title": "Вакцины", "is_service": 0},
        "goodSaleParams": [{"price": "5000", "coefficient": "1", "is_last": 1, "status": "active"}],
    },
]


@pytest.mark.django_db
def test_services_from_vetmanager_are_imported(monkeypatch) -> None:
    """«Вакдерм» в группе «Вакцинации» — услуга, и она тоже должна доехать."""
    monkeypatch.setattr(client, "fetch", lambda *a, **kw: VM_GOODS)

    out = StringIO()
    call_command("import_missing_items", "--apply", stdout=out)

    assert Item.objects.get(name="Вакдерм").kind == Kind.SERVICE
    assert Item.objects.get(name="Вакдерм-F уп.10 доз").kind == Kind.GOODS


@pytest.mark.django_db
def test_preview_counts_services_and_goods(monkeypatch) -> None:
    monkeypatch.setattr(client, "fetch", lambda *a, **kw: VM_GOODS)

    out = StringIO()
    call_command("import_missing_items", stdout=out)

    assert "нет у нас: 2" in out.getvalue()
    assert "1 услуга" in out.getvalue() and "1 товар" in out.getvalue()
    assert not Item.objects.filter(name="Вакдерм").exists()  # без --apply не переносим


@pytest.mark.django_db
def test_deleted_item_is_not_brought_back(monkeypatch) -> None:
    """Позицию, удалённую у нас, заново не заводим: её могли объединить с другой,
    и дубль сломал бы разобранный прайс. Для таких связей есть repair_item_links."""
    monkeypatch.setattr(client, "fetch", lambda *a, **kw: VM_GOODS)
    call_command("import_missing_items", "--apply", stdout=StringIO())
    catalog.delete_item(Item.objects.get(name="Вакдерм"))

    call_command("import_missing_items", "--apply", stdout=StringIO())

    assert not Item.objects.filter(name="Вакдерм").exists()
    assert Imported.objects.filter(kind="item", external_id="38").count() == 1
