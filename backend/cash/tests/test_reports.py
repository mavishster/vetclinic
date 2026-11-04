"""Отчёты: продажи и деньги по дням, популярное, должники, движение товара, выгрузка в Excel."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.test import APIClient

from billing import services as billing
from billing.models import Invoice
from cash import services as cash
from cash.models import CashRegister
from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from clients import services as clients
from clients.models import Client
from core import services as core
from inventory import services as inventory
from inventory.models import StockDocument, Warehouse

D = Decimal


@pytest.fixture
def data(db):
    client = clients.save_client(Client(last_name="Петров"))
    service = catalog.save_item(
        Item(kind=Kind.SERVICE, name="Приём", group=ItemGroup.objects.get(name="Приём и консультации"),
             base_unit=Unit.objects.get(name="усл."), manual_cost=D("200")),
        [{"unit": Unit.objects.get(name="усл."), "price": D("1000")}],
    ).units.get()  # fmt: skip
    drug = catalog.save_item(
        Item(
            kind=Kind.GOODS,
            name="Мильбемакс",
            group=ItemGroup.objects.get(name="Препараты"),
            base_unit=Unit.objects.get(name="таб."),
        ),
        [{"unit": Unit.objects.get(name="таб."), "price": D("350")}],
    )
    receipt = inventory.save_document(
        StockDocument(kind="receipt", warehouse=Warehouse.objects.get(name="Основной склад")),
        [{"item_unit": drug.units.get(), "quantity": D("10"), "price": D("150")}],
    )
    core.execute_document(receipt)
    paid = core.execute_document(
        billing.save_invoice(Invoice(client=client), [{"item_unit": service, "quantity": D("2")}])
    )
    cash.pay(
        {
            "client": client,
            "invoice_ids": [paid.pk],
            "cash_register": CashRegister.objects.get(name="Наличные"),
            "cash_received": D("2000"),
        }
    )
    unpaid = core.execute_document(
        billing.save_invoice(
            Invoice(client=client), [{"item_unit": drug.units.get(), "quantity": D("3")}]
        )
    )
    return {"client": client, "drug": drug, "unpaid": unpaid}


def test_sales_and_top_items(data) -> None:
    today = timezone.localdate()

    sales = billing.sales_by_day(today, today)
    top = billing.top_items(today, today)

    assert sales[0]["invoices"] == 2 and sales[0]["total"] == D("3050.00")
    assert [(r["name"], r["amount"]) for r in top] == [
        ("Приём", D("2000.00")),
        ("Мильбемакс", D("1050.00")),
    ]
    assert top[1]["cost"] == D("450.00")  # 3 × 150 из партии


def test_debtors_and_money(data) -> None:
    today = timezone.localdate()

    debtors = billing.debtors()
    money = cash.money_by_day(today, today)

    assert [(d["name"], d["debt"], d["invoices"]) for d in debtors] == [("Петров", D("1050.00"), 1)]
    assert money[0]["cash_in"] == D("2000.00")


def test_money_counts_only_client_payments(data) -> None:
    from cash.models import CashOperation

    user = get_user_model().objects.create_user(username="kassa", password="x")
    register = CashRegister.objects.get(name="Наличные")
    cash.operate(
        CashOperation(kind="income", register=register, amount=D("5000"), purpose="Размен"), user
    )
    cash.operate(
        CashOperation(
            kind="transfer",
            register=register,
            target_register=CashRegister.objects.get(name="Терминал"),
            amount=D("1000"),
        ),
        user,
    )
    cash.operate(
        CashOperation(kind="expense", register=register, amount=D("300"), purpose="Хозрасходы"),
        user,
    )
    today = timezone.localdate()

    money = cash.money_by_day(today, today)[0]

    assert (money["cash_in"], money["card_in"], money["out"]) == (D("2000.00"), D("0"), D("300.00"))


def test_turnover(data) -> None:
    today = timezone.localdate()

    rows = inventory.turnover(today, today)

    assert [
        (r["name"], r["opening"], r["incoming"], r["outgoing"], r["closing"]) for r in rows
    ] == [("Мильбемакс", D("0"), D("10.000"), D("3.000"), D("7.000"))]


def test_report_api_excel_and_cost_hidden(data) -> None:
    admin = APIClient()
    admin.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    role = Group.objects.create(name="Регистратор")
    core.set_entity_permissions(role, "billing.invoice", {"view"})
    viewer_user = get_user_model().objects.create_user(username="v", password="x")
    viewer_user.groups.add(role)
    viewer = APIClient()
    viewer.force_authenticate(viewer_user)

    excel = admin.get("/api/billing/reports/sales/?export=xlsx")
    top_admin = admin.get("/api/billing/reports/top-items/").json()
    top_viewer = viewer.get("/api/billing/reports/top-items/").json()
    money = admin.get("/api/cash/reports/money/").json()
    turnover = admin.get("/api/inventory/reports/turnover/?export=xlsx")
    bad = admin.get("/api/billing/reports/sales/?from=2026-12-01&to=2026-11-01")

    assert excel["Content-Type"].startswith("application/vnd.openxml")
    assert top_admin[1]["cost"] == "450.00" and top_viewer[1]["cost"] is None
    assert money[0]["cash_in"] == "2000.00"
    assert turnover.status_code == 200
    assert bad.status_code == 400
    assert viewer.get("/api/cash/reports/money/").status_code == 403


def test_refunded_payment_vanishes_from_money_report(data) -> None:
    from cash.models import Payment

    payment = Payment.objects.filter(status="executed").first()
    core.rollback_document(payment)  # оплату вернули (смена открыта)
    today = timezone.localdate()

    money = cash.money_by_day(today, today)

    assert money == [] or (money[0]["cash_in"], money[0]["out"]) == (D("0"), D("0"))
