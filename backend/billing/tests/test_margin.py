"""Прибыль счёта и приёма: выручка − себестоимость, у черновика — ожидаемая себестоимость."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from billing import services
from billing.models import Invoice
from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from clients import services as clients
from clients.models import Client
from core import services as core
from inventory import services as inventory
from inventory.models import StockDocument, Warehouse

D = Decimal


@pytest.fixture
def owner(db):
    return clients.save_client(Client(last_name="Петров"))


@pytest.fixture
def vial(db):
    """Флакон: продажа 700, закупка 400."""
    item = catalog.save_item(
        Item(kind=Kind.GOODS, name="Фелиферон", group=ItemGroup.objects.get(name="Препараты"), base_unit=Unit.objects.get(name="фл.")),
        [{"unit": Unit.objects.get(name="фл."), "price": D("700")}],
    )  # fmt: skip
    core.execute_document(inventory.save_document(
        StockDocument(kind="receipt", warehouse=Warehouse.objects.get(name="Оперативный склад")),
        [{"item_unit": item.units.get(), "quantity": D("10"), "price": D("400")}],
    ))  # fmt: skip
    return item.units.get()


@pytest.fixture
def service(db):
    """Услуга: цена 1000, себестоимость из карточки 200."""
    item = catalog.save_item(
        Item(kind=Kind.SERVICE, name="Приём", group=ItemGroup.objects.get(name="Приём и консультации"),
             base_unit=Unit.objects.get(name="усл."), manual_cost=D("200")),
        [{"unit": Unit.objects.get(name="усл."), "price": D("1000")}],
    )  # fmt: skip
    return item.units.get()


def test_draft_uses_expected_cost(owner, vial, service) -> None:
    invoice = services.save_invoice(
        Invoice(client=owner), [{"item_unit": vial, "quantity": D("2")}, {"item_unit": service}]
    )

    margin = services.invoice_margin(invoice)

    assert (margin["revenue"], margin["cost"], margin["profit"]) == (
        D("2400.00"),
        D("1000.00"),
        D("1400.00"),
    )
    assert margin["margin"] == D("58.3") and margin["unknown_cost"] == 0


def test_executed_uses_actual_batch_cost(owner, vial, service) -> None:
    invoice = core.execute_document(
        services.save_invoice(
            Invoice(client=owner), [{"item_unit": vial, "quantity": D("2")}, {"item_unit": service}]
        )
    )

    margin = services.invoice_margin(invoice)

    assert (margin["cost"], margin["profit"]) == (D("1000.00"), D("1400.00"))


def test_discount_lowers_profit(owner, service) -> None:
    invoice = services.save_invoice(
        Invoice(client=owner), [{"item_unit": service, "discount_percent": D("10")}]
    )

    margin = services.invoice_margin(invoice)

    assert (margin["revenue"], margin["cost"], margin["profit"]) == (
        D("900.00"),
        D("200.00"),
        D("700.00"),
    )


def test_unknown_cost_is_counted(owner) -> None:
    no_cost = catalog.save_item(
        Item(kind=Kind.SERVICE, name="Консультация", group=ItemGroup.objects.get(name="Приём и консультации"), base_unit=Unit.objects.get(name="усл.")),
        [{"unit": Unit.objects.get(name="усл."), "price": D("500")}],
    )  # fmt: skip
    invoice = services.save_invoice(Invoice(client=owner), [{"item_unit": no_cost.units.get()}])

    margin = services.invoice_margin(invoice)

    assert margin["unknown_cost"] == 1 and margin["profit"] == D("500.00")


def test_margin_in_api_only_with_right(owner, service, django_user_model) -> None:
    from django.contrib.auth.models import Group

    invoice = services.save_invoice(Invoice(client=owner), [{"item_unit": service}])
    admin = APIClient()
    admin.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    role = Group.objects.create(name="Кассир без себестоимости")
    core.set_entity_permissions(role, "billing.invoice", {"view"})
    user = django_user_model.objects.create_user(username="u", password="x")
    user.groups.add(role)
    plain = APIClient()
    plain.force_authenticate(user)

    full = admin.get(f"/api/billing/invoices/{invoice.pk}/").json()
    limited = plain.get(f"/api/billing/invoices/{invoice.pk}/").json()

    assert full["margin"] == {
        "revenue": "1000.00",
        "cost": "200.00",
        "profit": "800.00",
        "margin": "80.0",
        "unknown_cost": 0,
    }
    assert limited["margin"] is None


def test_visit_margin_sums_invoices(owner, vial, service, django_user_model) -> None:
    from django.utils import timezone

    from clients.models import Breed, Pet
    from medical import services as medical
    from medical.models import Visit
    from scheduling.models import VisitPurpose

    breed = Breed.objects.first()
    pet = clients.save_pet(Pet(name="Барсик", species=breed.species, breed=breed, owner=owner))
    doctor = django_user_model.objects.create_user(username="doc", password="x")
    visit = medical.save_visit(
        Visit(
            pet=pet,
            client=owner,
            doctor=doctor,
            date=timezone.now(),
            purpose=VisitPurpose.objects.first(),
        )
    )
    services.save_invoice(Invoice(client=owner, pet=pet, visit=visit), [{"item_unit": service}])
    services.save_invoice(Invoice(client=owner, pet=pet, visit=visit), [{"item_unit": vial}])

    margin = services.visit_margin(visit)

    assert (margin["revenue"], margin["cost"], margin["profit"]) == (
        D("1700.00"),
        D("600.00"),
        D("1100.00"),
    )
    assert margin["margin"] == D("64.7")
