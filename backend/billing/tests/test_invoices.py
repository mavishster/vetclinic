"""Счета: строки, цены, скидки, комбинации, выполнение со списанием, откат, баланс, отчёт."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from billing import services
from billing.models import Invoice
from billing.services import InvoiceError
from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from clients import services as clients
from clients.models import Breed, Client, Pet, Species
from core import services as core
from inventory import services as inventory
from inventory.models import StockDocument, Warehouse

D = Decimal


@pytest.fixture
def doctor(db):
    return get_user_model().objects.create_user(username="doc", password="x", last_name="Иванова")


@pytest.fixture
def client_(db):
    return clients.save_client(Client(last_name="Петров"))


@pytest.fixture
def visit_service(db):
    return catalog.save_item(
        Item(
            kind=Kind.SERVICE,
            name="Приём",
            group=ItemGroup.objects.get(name="Приём и консультации"),
            base_unit=Unit.objects.get(name="усл."),
        ),
        [
            {
                "unit": Unit.objects.get(name="усл."),
                "price": D("1000"),
                "price_min": D("800"),
                "price_max": D("1500"),
            }
        ],
    ).units.get()


@pytest.fixture
def vial(db):
    """Фелиферон: учёт во флаконах, упаковка = 5 фл."""
    item = catalog.save_item(
        Item(kind=Kind.GOODS, name="Фелиферон", group=ItemGroup.objects.get(name="Препараты"), base_unit=Unit.objects.get(name="фл.")),
        [{"unit": Unit.objects.get(name="фл."), "price": D("700")},
         {"unit": Unit.objects.get(name="упак."), "ratio": D("5"), "price": D("3500"), "for_purchase": True}],
    )  # fmt: skip
    receipt = inventory.save_document(
        StockDocument(kind="receipt", warehouse=Warehouse.objects.get(name="Основной склад")),
        [{"item_unit": item.units.get(unit__name="упак."), "quantity": D("2"), "price": D("2000")}],
    )
    core.execute_document(receipt)
    return item.units.get(unit__name="фл.")


def make(client, lines, **fields):
    return services.save_invoice(Invoice(client=client, **fields), lines)


def test_lines_prices_and_totals(client_, visit_service, vial, doctor) -> None:
    invoice = make(
        client_,
        [{"item_unit": visit_service}, {"item_unit": vial, "quantity": D("2")}],
        doctor=doctor,
    )

    assert [(line.price, line.amount) for line in invoice.lines.all()] == [
        (D("1000.00"), D("1000.00")),
        (D("700.00"), D("1400.00")),
    ]
    assert (invoice.subtotal, invoice.discount_total, invoice.total) == (
        D("2400.00"),
        D("0"),
        D("2400.00"),
    )
    assert {line.performer_id for line in invoice.lines.all()} == {doctor.pk}
    assert invoice.warehouse.name == "Основной склад"


def test_price_within_min_max_only(client_, visit_service) -> None:
    invoice = make(client_, [{"item_unit": visit_service, "price": D("900")}])
    assert invoice.lines.get().manual_price

    with pytest.raises(InvoiceError, match="вне допустимых границ"):
        make(client_, [{"item_unit": visit_service, "price": D("500")}])


def test_line_discounts_within_limits(client_, visit_service, vial) -> None:
    invoice = make(client_, [{"item_unit": visit_service, "discount_percent": D("10")},
                             {"item_unit": vial, "quantity": D("2"), "discount_percent": D("5")}])  # fmt: skip

    service, goods = invoice.lines.all()
    assert (service.discount, goods.discount) == (D("100.00"), D("70.00"))
    with pytest.raises(InvoiceError, match="больше допустимой на товар \\(5 %\\)"):
        make(client_, [{"item_unit": vial, "discount_percent": D("6")}])
    with pytest.raises(InvoiceError, match="больше допустимой на услугу \\(10 %\\)"):
        make(client_, [{"item_unit": visit_service, "discount_percent": D("11")}])


def test_discount_never_below_cost(client_, vial) -> None:
    clinic = core.current_clinic()
    clinic.max_discount_goods = D("50")
    clinic.save()

    # цена 700, себестоимость 400 (упаковка 2000 / 5 фл.) → не больше 42,85 %
    with pytest.raises(InvoiceError, match="ниже себестоимости — не больше 42,85 %"):
        make(client_, [{"item_unit": vial, "discount_percent": D("45")}])
    assert make(client_, [{"item_unit": vial, "discount_percent": D("42")}]).total == D("406.00")
    fresh = vial.__class__.objects.select_related("item").get(pk=vial.pk)
    assert services.discount_limit(fresh, D("700"))["percent"] == D("42.85")


def test_manual_price_has_no_discount_and_client_card_discount_respects_limits(
    client_, visit_service, vial
) -> None:
    invoice = make(
        client_, [{"item_unit": visit_service, "price": D("900"), "discount_percent": D("10")}]
    )
    assert invoice.lines.get().discount == D("0")

    client_.discount_percent = D("8")
    client_.save()
    invoice = make(client_, [{"item_unit": visit_service}, {"item_unit": vial}])
    service, goods = invoice.lines.all()
    assert (service.discount_percent, goods.discount_percent) == (D("8"), None)  # товару 8 % нельзя


def test_discount_amount_spreads_over_lines_without_own_discount(
    client_, visit_service, vial
) -> None:
    invoice = make(
        client_, [{"item_unit": visit_service}, {"item_unit": vial}], discount_amount=D("50")
    )

    assert sum(line.discount for line in invoice.lines.all()) == D("50")
    assert invoice.total == D("1650.00")
    with pytest.raises(
        InvoiceError, match="скидка суммой даёт 5,88 % — больше допустимой на товар"
    ):
        make(client_, [{"item_unit": visit_service}, {"item_unit": vial}], discount_amount=D("100"))
    with pytest.raises(InvoiceError, match="больше суммы"):
        make(client_, [{"item_unit": vial}], discount_amount=D("1000"))
    own = make(client_, [{"item_unit": visit_service, "discount_percent": D("10")}, {"item_unit": vial}],
               discount_amount=D("20"))  # fmt: skip
    assert [line.discount for line in own.lines.all()] == [D("100.00"), D("20.00")]


def test_combo_one_line_with_composition(client_, visit_service, vial) -> None:
    combo = catalog.save_combination(Item(name="Иммунокоррекция", group=ItemGroup.objects.get(name="Процедуры и манипуляции")),
                                     [{"item_unit": visit_service, "price_override": D("0")}, {"item_unit": vial, "quantity": D("2")}])  # fmt: skip

    invoice = make(client_, [{"item": combo, "quantity": D("1")}])

    header = invoice.lines.get(parent=None)
    assert header.item == combo and header.amount == D("1400.00")
    assert [c.item.name for c in header.children.all()] == ["Приём", "Фелиферон"]
    assert invoice.total == D("1400.00")


def test_combo_discount_by_composition(client_, visit_service, vial) -> None:
    combo = catalog.save_combination(Item(name="Вакцинация+", group=ItemGroup.objects.get(name="Процедуры и манипуляции")),
                                     [{"item_unit": visit_service}, {"item_unit": vial}])  # fmt: skip

    invoice = make(client_, [{"item": combo, "discount_percent": D("8")}])

    header = invoice.lines.get(parent=None)
    service, goods = header.children.all()
    assert (service.discount_percent, goods.discount_percent) == (
        D("8"),
        None,
    )  # товару 8 % нельзя — без скидки
    assert header.discount == D("80.00")


def test_combo_only_item_not_alone(client_, vial) -> None:
    vial.item.combo_only = True
    vial.item.save()

    with pytest.raises(InvoiceError, match="только в составе"):
        make(client_, [{"item_unit": vial}])


def test_execute_writes_off_stock_records_cost_and_debt(client_, vial, visit_service) -> None:
    invoice = make(client_, [{"item_unit": vial, "quantity": D("3")}, {"item_unit": visit_service}])

    core.execute_document(invoice)

    goods = invoice.lines.get(item=vial.item)
    assert goods.cost == D("1200.00")  # 3 фл. × 400 (2000 сом за упаковку из 5 фл.)
    assert goods.batches.get().qty_base == D("3")
    assert inventory.available(vial.item) == D("7")
    assert clients.balance(client_) == D("-3100.00")


def test_not_enough_stock_is_explained_when_negative_forbidden(client_, vial, settings) -> None:
    settings.ALLOW_NEGATIVE_STOCK = False
    invoice = make(client_, [{"item_unit": vial, "quantity": D("20")}])

    with pytest.raises(InvoiceError, match="Не хватает «Фелиферон».*Оформите приход"):
        core.execute_document(invoice)
    assert inventory.available(vial.item) == D("10")


def test_rollback_returns_stock_and_debt_to_draft(client_, vial) -> None:
    invoice = core.execute_document(make(client_, [{"item_unit": vial, "quantity": D("2")}]))

    core.rollback_document(invoice)

    assert invoice.status == "draft"
    assert inventory.available(vial.item) == D("10")
    assert clients.balance(client_) == D("0")
    assert invoice.lines.get().cost == D("0")


def test_invoice_from_visit_collects_mentions(client_, vial, visit_service, doctor) -> None:
    from medical import services as medical

    cats = Species.objects.get(name="Кошки")
    pet = clients.save_pet(
        Pet(
            owner=client_,
            name="Барсик",
            species=cats,
            breed=Breed.objects.get(name="Метис", species=cats),
        )
    )
    visit = medical.start_visit(pet, doctor)
    visit.treatment_html = f'<span data-item-unit="{visit_service.pk}">x</span><span data-item-unit="{vial.pk}">y</span>'
    medical.save_visit(visit)

    invoice = services.invoice_for_visit(visit)
    again = services.invoice_for_visit(visit)

    assert again.pk == invoice.pk
    assert invoice.pet == pet and invoice.doctor == doctor
    assert sorted(line.item.name for line in invoice.lines.all()) == ["Приём", "Фелиферон"]


def test_revenue_by_performer(client_, visit_service, doctor) -> None:
    other = get_user_model().objects.create_user(
        username="doc2", password="x", last_name="Сидорова"
    )
    core.execute_document(
        make(
            client_,
            [
                {"item_unit": visit_service, "performer": doctor},
                {"item_unit": visit_service, "performer": other, "price": D("1200")},
            ],
        )
    )
    make(client_, [{"item_unit": visit_service, "performer": doctor}])  # черновик не считается

    rows = services.revenue_by_performer(timezone.localdate(), timezone.localdate())

    assert [(r["name"], r["amount"]) for r in rows] == [
        ("Сидорова", D("1200.00")),
        ("Иванова", D("1000.00")),
    ]


def test_negative_sale_uses_last_batch_cost_and_receipt_closes_it(client_, vial) -> None:
    # на складе 10 фл. по 400; продаём 12
    invoice = core.execute_document(make(client_, [{"item_unit": vial, "quantity": D("12")}]))

    item = vial.item
    assert inventory.available(item) == D("-2")
    assert invoice.lines.get().cost == D("4800.00")  # 12 × 400 — по цене последней партии
    assert [r["qty"] for r in inventory.negative_stock()] == [D("-2")]

    receipt = inventory.save_document(
        StockDocument(kind="receipt", warehouse=Warehouse.objects.get(name="Основной склад")),
        [{"item_unit": item.units.get(unit__name="упак."), "quantity": D("1"), "price": D("2500")}],
    )
    core.execute_document(receipt)

    assert inventory.available(item) == D("3")
    assert inventory.negative_stock() == []
    assert [s.qty for s in inventory.batch_stock(item)] == [D("3")]  # минус закрыт новой партией


def test_rollback_of_negative_sale_returns_stock(client_, vial) -> None:
    invoice = core.execute_document(make(client_, [{"item_unit": vial, "quantity": D("12")}]))

    core.rollback_document(invoice)

    assert inventory.available(vial.item) == D("10")


def test_cost_source_explains_unit_conversion(client_, vial) -> None:
    pack = vial.__class__.objects.select_related("item__base_unit", "unit").get(
        item_id=vial.item_id, unit__name="упак."
    )
    fresh = vial.__class__.objects.select_related("item__base_unit", "unit").get(pk=vial.pk)

    cost, source = services.unit_cost_info(fresh)
    pack_cost, pack_source = services.unit_cost_info(pack)

    assert cost == D("400.00") and "400,00" in source and "за 1 фл." in source
    assert pack_cost == D("2000.00") and "1 упак. = 5 фл." in pack_source


def test_combo_separate_discounts_for_goods_and_services(client_, visit_service, vial) -> None:
    combo = catalog.save_combination(Item(name="Вакцинация++", group=ItemGroup.objects.get(name="Процедуры и манипуляции")),
                                     [{"item_unit": visit_service}, {"item_unit": vial}])  # fmt: skip

    invoice = make(
        client_, [{"item": combo, "goods_discount": D("5"), "services_discount": D("10")}]
    )

    service, goods = invoice.lines.get(parent=None).children.all()
    assert (service.discount_percent, goods.discount_percent) == (D("10"), D("5"))
