"""Единицу учёта можно исправить, пока по товару нет количеств.

Тест живёт здесь, а не в каталоге: он обращается к складу, а каталог модулем склада
пользоваться не может (уровни модулей, ENGINEERING.md).
"""

from decimal import Decimal

import pytest

from catalog import services
from catalog.models import Item, ItemGroup, Kind, Unit
from core import services as core
from inventory import services as inventory
from inventory.models import StockDocument, Warehouse


@pytest.fixture
def drug(db):
    return services.save_item(
        Item(
            kind=Kind.GOODS,
            name="Ветпрепарат",
            group=ItemGroup.objects.filter(kind=Kind.GOODS).first(),
            base_unit=Unit.objects.get(name="шт."),
        ),
        [{"unit": Unit.objects.get(name="шт."), "price": Decimal("10")}],
    )


def test_base_unit_can_change_until_first_receipt_or_sale(drug) -> None:
    """Единица учёта исправляется, пока по товару нет количеств — даже если стоит отметка
    «ведётся складской учёт» (после переноса прайса она есть у всех товаров)."""
    services.mark_stock_tracked(drug)
    drug.base_unit = Unit.objects.get(name="фл.")
    services.save_item(drug, [{"unit": drug.base_unit, "price": Decimal("10")}])  # прихода не было

    receipt = inventory.save_document(
        StockDocument(kind="receipt", warehouse=Warehouse.objects.get(name="Основной склад")),
        [{"item_unit": drug.units.get(), "quantity": Decimal("5"), "price": Decimal("3")}],
    )
    drug.base_unit = Unit.objects.get(name="шт.")
    with pytest.raises(services.CatalogError, match="нельзя менять после первого прихода"):
        services.save_item(drug)  # есть складской документ, даже черновик

    receipt.delete()
    services.save_item(drug, [{"unit": drug.base_unit, "price": Decimal("10")}])  # убрали — можно
    core.execute_document(
        inventory.save_document(
            StockDocument(kind="receipt", warehouse=Warehouse.objects.get(name="Основной склад")),
            [{"item_unit": drug.units.get(), "quantity": Decimal("5"), "price": Decimal("3")}],
        )
    )
    drug.base_unit = Unit.objects.get(name="фл.")
    with pytest.raises(services.CatalogError, match="нельзя менять после первого прихода"):
        services.save_item(drug)
