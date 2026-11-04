"""Касса: оплата со сдачей и авансом, распределение на счета, возврат, операции, смены."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from billing import services as billing
from billing.models import Invoice
from cash import services
from cash.models import CashOperation, CashRegister
from cash.services import CashError
from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from clients import services as clients
from clients.models import Client
from core import services as core

D = Decimal


@pytest.fixture
def user(db):
    user = get_user_model().objects.create_user(username="admin2", password="x", last_name="Орлова")
    core.set_pin(user, "4826")
    return user


@pytest.fixture
def client_(db):
    return clients.save_client(Client(last_name="Петров"))


@pytest.fixture
def service(db):
    return catalog.save_item(
        Item(
            kind=Kind.SERVICE,
            name="Приём",
            group=ItemGroup.objects.get(name="Приём и консультации"),
            base_unit=Unit.objects.get(name="усл."),
        ),
        [{"unit": Unit.objects.get(name="усл."), "price": D("1000")}],
    ).units.get()


@pytest.fixture
def cash(db):
    return CashRegister.objects.get(name="Наличные")


@pytest.fixture
def card(db):
    return CashRegister.objects.get(name="Терминал")


def invoice(client, service, qty="1"):
    return core.execute_document(
        billing.save_invoice(Invoice(client=client), [{"item_unit": service, "quantity": D(qty)}])
    )


def refresh(obj):
    obj.refresh_from_db()
    return obj


def test_cash_payment_with_change(client_, service, cash) -> None:
    inv = invoice(client_, service)

    payment = services.pay(
        {
            "client": client_,
            "invoice_ids": [inv.pk],
            "cash_register": cash,
            "cash_received": D("1500"),
        }
    )

    assert payment.change_given == D("500.00")
    assert services.balance(cash) == D("1000.00")
    assert refresh(inv).payment_status == "paid"
    assert clients.balance(client_) == D("0")


def test_change_to_balance_becomes_advance_and_pays_next_invoice(client_, service, cash) -> None:
    first = invoice(client_, service)
    services.pay(
        {
            "client": client_,
            "invoice_ids": [first.pk],
            "cash_register": cash,
            "cash_received": D("1500"),
            "change_to_balance": True,
        }
    )

    assert billing.client_credit(client_) == D("500.00")
    second = invoice(client_, service)

    assert refresh(second).paid_amount == D("500.00")  # аванс зачёлся сам
    assert refresh(second).payment_status == "partial"
    assert services.balance(cash) == D("1500.00")


def test_mixed_and_partial_payment(client_, service, cash, card) -> None:
    inv = invoice(client_, service, qty="2")  # 2000

    services.pay({"client": client_, "invoice_ids": [inv.pk], "cash_register": cash, "card_register": card,
                  "cash_received": D("500"), "card_amount": D("1000")})  # fmt: skip

    assert refresh(inv).paid_amount == D("1500.00")
    assert refresh(inv).payment_status == "partial"
    assert (services.balance(cash), services.balance(card)) == (D("500.00"), D("1000.00"))
    assert clients.balance(client_) == D("-500.00")  # долг


def test_one_payment_for_selected_invoices_only(client_, service, cash) -> None:
    a, b, c = invoice(client_, service), invoice(client_, service), invoice(client_, service)

    services.pay(
        {
            "client": client_,
            "invoice_ids": [a.pk, c.pk],
            "cash_register": cash,
            "cash_received": D("2000"),
        }
    )

    assert [refresh(x).payment_status for x in (a, b, c)] == ["paid", "debt", "paid"]


def test_card_overpay_and_wrong_registers_rejected(client_, service, cash, card) -> None:
    inv = invoice(client_, service)

    with pytest.raises(CashError, match="сдачу с карты"):
        services.pay(
            {
                "client": client_,
                "invoice_ids": [inv.pk],
                "card_register": card,
                "card_amount": D("1200"),
            }
        )
    with pytest.raises(CashError, match="кассу наличных"):
        services.pay(
            {
                "client": client_,
                "invoice_ids": [inv.pk],
                "cash_register": card,
                "cash_received": D("1000"),
            }
        )


def test_refund_while_shift_open_then_not_after_closing(client_, service, cash, user) -> None:
    inv = invoice(client_, service)
    payment = services.pay(
        {
            "client": client_,
            "invoice_ids": [inv.pk],
            "cash_register": cash,
            "cash_received": D("1000"),
        }
    )

    core.rollback_document(payment)
    assert refresh(inv).payment_status == "debt"
    assert services.balance(cash) == D("0")

    payment2 = services.pay(
        {
            "client": client_,
            "invoice_ids": [inv.pk],
            "cash_register": cash,
            "cash_received": D("1000"),
        }
    )
    shift = services.close_shift(cash, user)
    assert (shift.income, shift.closing_balance) == (D("2000.00"), D("1000.00"))
    with pytest.raises(CashError, match="Касса уже закрыта"):
        core.rollback_document(payment2)


def test_invoice_rollback_turns_payment_into_advance(client_, service, cash) -> None:
    inv = invoice(client_, service)
    services.pay(
        {
            "client": client_,
            "invoice_ids": [inv.pk],
            "cash_register": cash,
            "cash_received": D("1000"),
        }
    )

    core.rollback_document(inv)

    assert billing.client_credit(client_) == D("1000.00")
    assert clients.balance(client_) == D("1000.00")  # аванс
    core.execute_document(inv)  # исправили и выполнили снова — оплатился авансом
    assert refresh(inv).payment_status == "paid"


def test_advance_deposit_and_return_with_pin(client_, cash, user) -> None:
    services.pay({"client": client_, "cash_register": cash, "cash_received": D("3000")})
    assert billing.client_credit(client_) == D("3000.00")

    with pytest.raises(CashError, match="Неверный ПИН"):
        services.operate(
            CashOperation(kind="advance_return", register=cash, client=client_, amount=D("1000")),
            user,
            "0000",
        )
    services.operate(
        CashOperation(kind="advance_return", register=cash, client=client_, amount=D("1000")),
        user,
        "4826",
    )

    assert billing.client_credit(client_) == D("2000.00")  # можно вернуть часть
    assert services.balance(cash) == D("2000.00")
    with pytest.raises(CashError, match="вернуть больше нельзя"):
        services.operate(
            CashOperation(kind="advance_return", register=cash, client=client_, amount=D("5000")),
            user,
            "4826",
        )


def test_cash_operations_and_summary(cash, card, user) -> None:
    services.operate(
        CashOperation(kind="income", register=cash, amount=D("5000"), purpose="Размен"), user
    )
    services.operate(
        CashOperation(kind="transfer", register=cash, target_register=card, amount=D("1000")), user
    )
    services.operate(
        CashOperation(kind="expense", register=cash, amount=D("500"), purpose="Хозрасходы"), user
    )

    with pytest.raises(CashError, match="только 3\u00a0500,00\u00a0сом"):
        services.operate(CashOperation(kind="expense", register=cash, amount=D("9999")), user)
    rows = {r["name"]: r for r in services.summary()}
    assert rows["Наличные"]["balance"] == D("3500.00")
    assert rows["Наличные"]["shift_income"] == D("5000.00")
    assert rows["Терминал"]["balance"] == D("1000.00")


def test_update_details_of_executed_invoice(client_, service) -> None:
    inv = invoice(client_, service)
    other = get_user_model().objects.create_user(username="doc2", password="x")
    line = inv.lines.get()

    billing.update_details(inv, doctor=other, performers={str(line.pk): other.pk})

    assert refresh(inv).doctor == other
    assert line.__class__.objects.get(pk=line.pk).performer == other


def test_guest_quick_invoice_must_be_paid_in_full(service, cash) -> None:
    guest = clients.guest_client()
    assert clients.guest_client().pk == guest.pk  # один на клинику
    inv = invoice(guest, service)

    with pytest.raises(CashError, match="полностью"):
        services.pay(
            {
                "client": guest,
                "invoice_ids": [inv.pk],
                "cash_register": cash,
                "cash_received": D("500"),
            }
        )
    with pytest.raises(CashError, match="сдачу нужно выдать"):
        services.pay(
            {
                "client": guest,
                "invoice_ids": [inv.pk],
                "cash_register": cash,
                "cash_received": D("1500"),
                "change_to_balance": True,
            }
        )
    payment = services.pay(
        {
            "client": guest,
            "invoice_ids": [inv.pk],
            "cash_register": cash,
            "cash_received": D("2000"),
        }
    )

    assert payment.change_given == D("1000.00")
    assert refresh(inv).payment_status == "paid"


def test_negative_cash_in_payment_is_refused(db) -> None:
    from cash import services as cash
    from cash.models import CashRegister
    from clients import services as clients
    from clients.models import Client

    owner = clients.save_client(Client(last_name="Петров"))
    with pytest.raises(cash.CashError, match="отрицательными"):
        cash.pay({"client": owner, "invoice_ids": [], "cash_register": CashRegister.objects.get(name="Наличные"),
                  "cash_received": Decimal("-500"), "card_amount": Decimal("600")})  # fmt: skip
