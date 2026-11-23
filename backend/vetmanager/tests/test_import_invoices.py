"""Перенос счетов VetManager: история продаж, скидки и наценки, оплаты, повторный перенос.

Ответы VetManager — по боевой выгрузке клиники: price в строке — сумма строки до
скидки или наценки на счёт, amount в шапке — уже с ними.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from billing.models import Invoice, InvoiceLineBatch, InvoicePayment
from catalog.models import Item, ItemUnit, Unit
from clients import services as clients
from clients.models import Client, ClientLedger
from vetmanager import services
from vetmanager.tests.test_import import (
    BREEDS,
    CLIENTS,
    COMBO_ITEMS,
    GOODS,
    GROUPS,
    MEDICAL_CARDS,
    PET_TYPES,
    PETS,
    UNITS,
    VM_DIAGNOSES,
    VM_USERS,
)

D = Decimal


def head(number, status="exec", amount="900", paid=None, date="2026-03-14 11:00:00", **extra):
    paid = amount if paid is None else paid
    return {
        "id": number,
        "doctor_id": 3,
        "client_id": 100,
        "pet_id": 200,
        "description": "",
        "percent": "0.0000000000",
        "increase": "0.0000000000",
        "discount": "0.0000000000",
        "amount": amount,
        "paid_amount": paid,
        "status": status,
        "payment_status": "full" if D(paid) >= D(amount) else "partial" if D(paid) else "none",
        "invoice_date": date,
        "create_date": date,
        **extra,
    }


def line(good, quantity, price, title=""):
    return {
        "good_id": good,
        "quantity": quantity,
        "price": price,
        "default_price": price,
        "responsible_user_id": 0,
        "good": {"title": title},
    }


@pytest.fixture
def base(db, django_user_model):
    services.import_units(UNITS)
    services.import_item_groups(GROUPS)
    services.import_items(GOODS)
    services.import_species(PET_TYPES, BREEDS)
    services.import_clients(CLIENTS)
    services.import_pets(PETS)
    django_user_model.objects.create_user(
        username="petrova", last_name="Петрова", first_name="Анна"
    )
    services.import_doctors(VM_USERS, only_with_visits=False)


def pushkin():
    return Client.objects.get(journal_number="А-12")


def test_paid_invoice_with_discount(base) -> None:
    """Скидка на счёт из шапки VetManager — делится по строкам, итог как в VetManager."""
    heads = [head(66, amount="2160", percent="-10.0000000000", discount="10.0000000000")]
    lines = {"66": [line(3, "1", "900"), line(1, "1", "1500")]}

    result = services.import_invoices(heads, lines)

    assert (result.created, result.errors) == (1, [])
    invoice = Invoice.objects.get()
    assert invoice.is_executed and invoice.imported
    assert (invoice.subtotal, invoice.discount_total, invoice.total) == (
        D("2400.00"),
        D("240.00"),
        D("2160.00"),
    )
    assert invoice.paid_amount == D("2160.00") and invoice.payment_status == "paid"
    assert sum(row.amount for row in invoice.lines.all()) == D("2160.00")
    assert clients.balance(pushkin()) == 0  # начислено и оплачено — долга нет
    assert invoice.doctor.last_name == "Петрова" and invoice.pet.name == "Барсик"
    assert "счёт № 66" in invoice.comment


def test_history_does_not_touch_stock_and_keeps_dates(base) -> None:
    services.import_invoices([head(1, amount="1500")], {"1": [line(1, "1", "1500")]})

    invoice = Invoice.objects.get()
    assert not InvoiceLineBatch.objects.exists()  # склад не трогали
    assert str(invoice.date)[:10] == "2026-03-14"
    assert invoice.executed_at == invoice.date
    dates = {e.posted_at for e in ClientLedger.objects.filter(client=pushkin())}
    assert dates == {invoice.date}  # начисление и оплата — датой счёта


def test_surcharge_raises_line_price(base) -> None:
    """Наценка на счёт (increase, например ночью) — цена строки выше прайсовой."""
    heads = [head(30, amount="1800", increase="100.0000000000")]

    services.import_invoices(heads, {"30": [line(3, "1", "900")]})

    invoice = Invoice.objects.get()
    row = invoice.lines.get()
    assert (row.list_price, row.price, row.amount, row.manual_price) == (
        D("900.00"),
        D("1800.00"),
        D("1800.00"),
        True,
    )
    assert invoice.total == D("1800.00") and invoice.discount_total == 0


def test_partial_payment_leaves_debt(base) -> None:
    services.import_invoices([head(5, amount="1500", paid="500")], {"5": [line(1, "1", "1500")]})

    invoice = Invoice.objects.get()
    assert invoice.paid_amount == D("500.00") and invoice.payment_status == "partial"
    assert clients.balance(pushkin()) == D("-1000.00")  # долг как в VetManager


def test_open_invoice_becomes_draft_deleted_is_skipped(base) -> None:
    heads = [head(6, status="save", paid="0"), head(26, status="deleted")]
    lines = {"6": [line(3, "1", "900")], "26": [line(3, "1", "900")]}

    result = services.import_invoices(heads, lines)

    assert (result.created, result.gone) == (1, 1)
    draft = Invoice.objects.get()
    assert not draft.is_executed and draft.total == D("900.00")
    assert clients.balance(pushkin()) == 0  # черновик ничего не начисляет


def test_unit_by_price_after_merge(base) -> None:
    """Объединённая позиция: строка «по 50» — мл, строка «по 4000» — флакон."""
    drug = Item.objects.get(name="Энрофлоксацин")
    bottle = Unit.objects.get(name="фл.")
    ItemUnit.objects.create(item=drug, unit=bottle, ratio=D("100"), price=D("4000"))
    lines = {"7": [line(2, "2", "100"), line(2, "1", "4000")]}

    services.import_invoices([head(7, amount="4100")], lines)

    rows = list(Invoice.objects.get().lines.order_by("position"))
    assert [(r.item_unit.unit.name, r.quantity, r.qty_base) for r in rows] == [
        ("мл", D("2"), D("2")),
        ("фл.", D("1"), D("100")),
    ]


def test_missing_item_is_reported_not_imported(base) -> None:
    lines = {"8": [line(3, "1", "900"), line(999, "1", "300", "Оксигенотерапия 1 сутки")]}

    result = services.import_invoices([head(8, amount="1200")], lines)

    assert result.created == 0 and not Invoice.objects.exists()
    assert "Оксигенотерапия 1 сутки" in result.errors[0]


def test_visit_of_the_same_day_is_linked(base) -> None:
    services.import_diagnoses(VM_DIAGNOSES)
    services.import_visit_purposes(COMBO_ITEMS)
    services.import_visits(MEDICAL_CARDS, COMBO_ITEMS)

    services.import_invoices([head(9)], {"9": [line(3, "1", "900")]})

    invoice = Invoice.objects.get()
    assert invoice.visit is not None and invoice.visit.pet.name == "Барсик"


def test_rerun_unchanged_skips_paid_later_updates(base) -> None:
    lines = {"10": [line(1, "1", "1500")]}
    services.import_invoices([head(10, amount="1500", paid="0")], lines)
    assert clients.balance(pushkin()) == D("-1500.00")

    same = services.import_invoices([head(10, amount="1500", paid="0")], lines)
    paid_later = services.import_invoices([head(10, amount="1500", paid="1500")], lines)

    assert (same.skipped, same.updated) == (1, 0)
    assert (paid_later.updated, paid_later.created) == (1, 0)
    assert Invoice.objects.count() == 1
    assert Invoice.objects.get().payment_status == "paid"
    assert clients.balance(pushkin()) == 0
    # Откат и повторное начисление тоже записаны датой счёта: история баланса верна.
    invoice = Invoice.objects.get()
    assert set(
        ClientLedger.objects.filter(client=pushkin()).values_list("posted_at", flat=True)
    ) == {invoice.date}


def test_rerun_keeps_invoice_paid_here(base) -> None:
    """По счёту приняли деньги нашей кассой — перенос его больше не трогает."""
    lines = {"11": [line(1, "1", "1500")]}
    services.import_invoices([head(11, amount="1500", paid="0")], lines)
    invoice = Invoice.objects.get()
    InvoicePayment.objects.create(invoice=invoice, amount=D("100"), payment_id=uuid.uuid4())

    again = services.import_invoices([head(11, amount="1500", paid="1500")], lines)

    assert again.updated == 0 and len(again.kept) == 1
    assert InvoicePayment.objects.filter(payment_id__isnull=True).count() == 0


def test_invoices_go_in_date_order_and_status_counts(base) -> None:
    later = head(13, date="2026-03-20 10:00:00")
    earlier = head(12, date="2026-03-10 10:00:00")
    lines = {"12": [line(3, "1", "900")], "13": [line(3, "1", "900")]}

    services.import_invoices([later, earlier], lines)

    dates = list(Invoice.objects.order_by("number").values_list("date", flat=True))
    assert dates[0] < dates[1] and dates[1] - dates[0] == timedelta(days=10)
    status = {row["step"]: row["imported"] for row in services.status()}
    assert status["invoices"] == 2


# --- Остатки авансов и долгов ---------------------------------------------------------


def test_balances_bring_advance_from_vetmanager(base) -> None:
    """Депозит, внесённый в VetManager без счёта, — авансом у нас; повтор ничего не задваивает."""
    services.import_invoices([head(20, amount="1500", paid="500")], {"20": [line(1, "1", "1500")]})
    assert clients.balance(pushkin()) == D("-1000.00")
    rows = [{**CLIENTS[0], "balance": "14000.0000000000"}]

    first = services.import_balances(rows)
    again = services.import_balances(rows)

    assert (first.updated, again.updated, again.skipped) == (1, 0, 1)
    assert clients.balance(pushkin()) == D("14000.00")
    from clients.models import OpeningBalance

    opening = OpeningBalance.objects.get()
    assert opening.is_executed and opening.amount == D("15000.00")
    # Остаток не трогает статусы перенесённых счетов: они сверяются с VetManager дальше.
    assert Invoice.objects.get().paid_amount == D("500.00")


def test_balances_add_only_new_difference(base) -> None:
    services.import_balances([{**CLIENTS[0], "balance": "5000"}])

    result = services.import_balances([{**CLIENTS[0], "balance": "3000"}])

    assert result.updated == 1 and clients.balance(pushkin()) == D("3000.00")
