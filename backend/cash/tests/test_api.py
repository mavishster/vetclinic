from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from billing import services as billing
from billing.models import Invoice
from cash.models import CashRegister
from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from clients import services as clients
from clients.models import Client
from core import services as core

D = Decimal


@pytest.fixture
def admin(db):
    user = get_user_model().objects.create_superuser(username="a", password="x")
    core.set_pin(user, "4826")
    api = APIClient()
    api.force_authenticate(user)
    return api


@pytest.fixture
def unpaid(db):
    client = clients.save_client(Client(last_name="Петров"))
    unit = catalog.save_item(
        Item(
            kind=Kind.SERVICE,
            name="Приём",
            group=ItemGroup.objects.get(name="Приём и консультации"),
            base_unit=Unit.objects.get(name="усл."),
        ),
        [{"unit": Unit.objects.get(name="усл."), "price": D("1000")}],
    ).units.get()
    return core.execute_document(
        billing.save_invoice(Invoice(client=client), [{"item_unit": unit, "quantity": D("1")}])
    )


def test_pay_refund_summary_and_close(admin, unpaid) -> None:
    cash = str(CashRegister.objects.get(name="Наличные").pk)

    paid = admin.post(
        "/api/cash/payments/pay/",
        {
            "client": str(unpaid.client_id),
            "invoice_ids": [str(unpaid.pk)],
            "cash_register": cash,
            "cash_received": "1500",
        },
        format="json",
    )
    invoice = admin.get(f"/api/billing/invoices/{unpaid.pk}/").json()
    summary = {r["name"]: r for r in admin.get("/api/cash/cash/summary/").json()}
    refund = admin.post(f"/api/cash/payments/{paid.json()['id']}/refund/")
    closed = admin.post("/api/cash/cash/close-shift/", {"register": cash}, format="json")
    again = admin.post("/api/cash/cash/close-shift/", {"register": cash}, format="json")

    assert paid.status_code == 201 and paid.json()["change_given"] == "500.00"
    assert invoice["payment_status"] == "paid"
    assert summary["Наличные"]["balance"] == "1000.00"
    assert refund.json()["status"] == "draft"
    assert closed.json()["income"] == "1000.00" and closed.json()["closing_balance"] == "0.00"
    assert "не открыта" in again.json()["non_field_errors"][0]


def test_unpaid_filter_details_and_advance_return(admin, unpaid) -> None:
    cash = str(CashRegister.objects.get(name="Наличные").pk)
    other = get_user_model().objects.create_user(username="doc", password="x", last_name="Сидорова")

    listed = admin.get(f"/api/billing/invoices/?client={unpaid.client_id}&unpaid=1").json()[
        "results"
    ]
    details = admin.patch(
        f"/api/billing/invoices/{unpaid.pk}/details/", {"doctor": str(other.pk)}, format="json"
    )
    admin.post(
        "/api/cash/payments/pay/",
        {"client": str(unpaid.client_id), "cash_register": cash, "cash_received": "3000"},
        format="json",
    )
    bad_pin = admin.post(
        "/api/cash/operations/",
        {
            "kind": "advance_return",
            "register": cash,
            "client": str(unpaid.client_id),
            "amount": "500",
            "pin": "1111",
        },
        format="json",
    )
    returned = admin.post(
        "/api/cash/operations/",
        {
            "kind": "advance_return",
            "register": cash,
            "client": str(unpaid.client_id),
            "amount": "500",
            "pin": "4826",
        },
        format="json",
    )

    assert [i["id"] for i in listed] == [str(unpaid.pk)]
    assert details.json()["doctor"] == str(other.pk)
    assert "Неверный ПИН" in bad_pin.json()["non_field_errors"][0]
    assert returned.status_code == 201
    assert clients.balance(unpaid.client_id) == D(
        "1500.00"
    )  # 3000 аванса − 1000 долга − 500 вернули


def test_permissions(db) -> None:
    plain = APIClient()
    plain.force_authenticate(get_user_model().objects.create_user(username="u", password="x"))

    assert plain.get("/api/cash/payments/").status_code == 403
    assert plain.post("/api/cash/payments/pay/", {}, format="json").status_code == 403
    assert plain.get("/api/cash/cash/summary/").status_code == 403
