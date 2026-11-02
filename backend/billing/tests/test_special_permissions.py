"""Особые права и шаблоны ролей (проверяются на счетах — верхнем модуле, который видит всё нужное)."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from billing import services as billing
from billing.models import Invoice
from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from clients import services as clients
from clients.models import Client
from core import services

D = Decimal


def api_with_role(access: dict, special: list[str] | None = None) -> APIClient:
    role = Group.objects.create(name="Тестовая")
    for entity, actions in access.items():
        services.set_entity_permissions(role, entity, set(actions))
    services.set_special_permissions(role, set(special or []))
    user = get_user_model().objects.create_user(username="worker", password="x")
    user.groups.add(role)
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def executed_invoice(db):
    client = clients.save_client(Client(last_name="Петров"))
    unit = catalog.save_item(
        Item(kind=Kind.SERVICE, name="Приём", group=ItemGroup.objects.get(name="Приём и консультации"),
             base_unit=Unit.objects.get(name="усл."), manual_cost=D("300")),
        [{"unit": Unit.objects.get(name="усл."), "price": D("1000")}],
    ).units.get()  # fmt: skip
    return services.execute_document(
        billing.save_invoice(Invoice(client=client), [{"item_unit": unit, "quantity": D("1")}])
    )


def test_special_permissions_listed_per_module_and_saved_on_role(db) -> None:
    modules = {m["code"]: m for m in services.permission_modules()}
    role = Group.objects.create(name="Кассир")

    services.set_special_permissions(role, {"cash.refund_payment", "cash.close_shift"})

    assert [sp["code"] for sp in modules["billing"]["special"]] == ["billing.rollback_invoice"]
    assert services.special_of(role) == {"cash.refund_payment", "cash.close_shift"}
    with pytest.raises(ValueError):
        services.set_special_permissions(role, {"cash.fly"})


def test_rollback_needs_special_permission(executed_invoice) -> None:
    without = api_with_role({"billing.invoice": ["view", "edit"]})

    denied = without.post(f"/api/billing/invoices/{executed_invoice.pk}/rollback/")

    assert denied.status_code == 403
    assert "Откатывать выполненные и оплаченные счета" in denied.json()["detail"]


def test_rollback_allowed_with_special_permission(executed_invoice) -> None:
    allowed = api_with_role({"billing.invoice": ["view", "edit"]}, ["billing.rollback_invoice"])

    assert allowed.post(f"/api/billing/invoices/{executed_invoice.pk}/rollback/").status_code == 200


def test_cost_hidden_without_permission(executed_invoice) -> None:
    viewer = api_with_role({"billing.invoice": ["view"], "catalog.item": ["view", "edit"]})
    item = executed_invoice.lines.get().item

    invoice = viewer.get(f"/api/billing/invoices/{executed_invoice.pk}/").json()
    card = viewer.get(f"/api/catalog/items/{item.pk}/").json()
    viewer.patch(
        f"/api/catalog/items/{item.pk}/",
        {"name": "Приём врача", "manual_cost": None},
        format="json",
    )

    assert "cost" not in invoice["lines"][0]
    assert card["manual_cost"] is None
    item.refresh_from_db()
    assert item.manual_cost == D("300.00")  # не видел — не стёр


def test_role_api_special_and_templates(db) -> None:
    admin = APIClient()
    admin.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))

    templates = admin.get("/api/core/roles/templates/").json()
    cashier = next(t for t in templates if t["code"] == "cashier")
    created = admin.post(
        "/api/core/roles/",
        {"name": "Кассир", "access": cashier["access"], "special": cashier["special"]},
        format="json",
    )

    assert [t["name"] for t in templates] == [
        "Врач",
        "Регистратор",
        "Кассир",
        "Кладовщик",
        "Планшет подписи",
        "Руководитель",
    ]
    assert created.status_code == 201
    assert set(created.json()["special"]) == {
        "cash.refund_payment",
        "cash.return_advance",
        "cash.close_shift",
    }
    manager = next(t for t in templates if t["code"] == "manager")
    assert len(manager["special"]) == len(services.special_permissions()) - 1  # без права планшета
