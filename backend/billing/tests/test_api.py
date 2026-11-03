from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from clients import services as clients
from clients.models import Client

URL = "/api/billing/invoices/"


@pytest.fixture
def api(db):
    client = APIClient()
    client.force_authenticate(
        get_user_model().objects.create_superuser(username="a", password="x", last_name="Орлова")
    )
    return client


@pytest.fixture
def service(db):
    return catalog.save_item(
        Item(
            kind=Kind.SERVICE,
            name="Первичный приём",
            group=ItemGroup.objects.get(name="Приём и консультации"),
            base_unit=Unit.objects.get(name="усл."),
        ),
        [{"unit": Unit.objects.get(name="усл."), "price": Decimal("1000")}],
    ).units.get()


def test_invoice_flow(api, service) -> None:
    owner = clients.save_client(Client(last_name="Петров"))
    found = api.get(f"{URL}lookup/?search=первичный").json()

    created = api.post(URL, {"client": str(owner.pk),
                             "input_lines": [{"item_unit": found[0]["item_unit"], "quantity": "2", "discount_percent": "10"}]}, format="json")  # fmt: skip
    invoice = created.json()
    executed = api.post(f"{URL}{invoice['id']}/execute/").json()
    report = api.get("/api/billing/reports/performers/").json()
    pdf = api.get(f"{URL}{invoice['id']}/print/")
    blocked_delete = api.delete(f"{URL}{invoice['id']}/")
    rolled = api.post(f"{URL}{invoice['id']}/rollback/").json()

    assert created.status_code == 201
    assert invoice["total"] == "1800.00"
    assert executed["status"] == "executed" and executed["client_balance"] == "-1800.00"
    assert report[0]["amount"] == "1800.00"
    assert pdf["Content-Type"] == "application/pdf"
    assert blocked_delete.status_code == 400
    assert rolled["status"] == "draft" and rolled["client_balance"] == "0"


def test_readable_errors_and_permissions(api, service, db) -> None:
    owner = clients.save_client(Client(last_name="Петров"))
    bad = api.post(
        URL,
        {"client": str(owner.pk), "input_lines": [{"item_unit": str(service.pk), "quantity": "0"}]},
        format="json",
    )
    plain = APIClient()
    plain.force_authenticate(get_user_model().objects.create_user(username="u", password="x"))

    assert "больше нуля" in bad.json()["non_field_errors"][0]
    assert plain.get(URL).status_code == 403
    assert plain.get("/api/billing/reports/performers/").status_code == 403


def test_line_limits_cost_visibility_and_clinic_settings(api, service, db) -> None:
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group

    from core import services as core

    owner = clients.save_client(Client(last_name="Петров"))
    invoice = api.post(
        URL,
        {"client": str(owner.pk), "input_lines": [{"item_unit": str(service.pk)}]},
        format="json",
    ).json()
    line = invoice["lines"][0]
    assert line["max_discount"] == {"percent": "10.00", "reason": "limit"}

    settings = api.patch("/api/core/clinic/", {"max_discount_services": "7"}, format="json")
    again = api.get(f"{URL}{invoice['id']}/").json()
    bad = api.patch("/api/core/clinic/", {"max_discount_goods": "150"}, format="json")
    assert settings.json()["max_discount_services"] == "7.00"
    assert again["lines"][0]["max_discount"]["percent"] == "7.00"
    assert bad.status_code == 400

    role = Group.objects.create(name="Оператор без себестоимости")
    core.set_entity_permissions(role, "billing.invoice", {"view", "edit"})
    user = get_user_model().objects.create_user(username="op", password="x")
    user.groups.add(role)
    operator = APIClient()
    operator.force_authenticate(user)
    seen = operator.get(f"{URL}{invoice['id']}/").json()["lines"][0]
    assert "unit_cost" not in seen and seen["max_discount"]["percent"] == "7.00"
    assert (
        operator.patch("/api/core/clinic/", {"max_discount_goods": "3"}, format="json").status_code
        == 403
    )
