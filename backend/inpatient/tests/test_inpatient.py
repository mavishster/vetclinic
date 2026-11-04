"""Стационар: приём, места, лист назначений, отметки, перенос из медкарты, выписка, счёт."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from clients import services as clients
from clients.models import Breed, Client, Pet, Species
from core import services as core
from core.models import PrintTemplate
from inpatient import services
from inpatient.models import TreatmentTask, Ward
from inpatient.services import InpatientError
from medical import services as medical

D = Decimal


@pytest.fixture
def doctor(db):
    return get_user_model().objects.create_user(username="doc", password="x", last_name="Иванова")


@pytest.fixture
def pet(db):
    owner = clients.save_client(Client(last_name="Петров"))
    cats = Species.objects.get(name="Кошки")
    return clients.save_pet(
        Pet(
            owner=owner,
            name="Барсик",
            species=cats,
            breed=Breed.objects.get(name="Метис", species=cats),
        )
    )


@pytest.fixture
def ward(db):
    day = catalog.save_item(
        Item(kind=Kind.SERVICE, name="Сутки стационара", group=ItemGroup.objects.get(name="Стационар"), base_unit=Unit.objects.get(name="сут.")),
        [{"unit": Unit.objects.get(name="сут."), "price": D("1500")}],
    ) if Unit.objects.filter(name="сут.").exists() else catalog.save_item(
        Item(kind=Kind.SERVICE, name="Сутки стационара", group=ItemGroup.objects.get(name="Стационар"), base_unit=Unit.objects.get(name="усл.")),
        [{"unit": Unit.objects.get(name="усл."), "price": D("1500")}],
    )  # fmt: skip
    return Ward.objects.create(name="Бокс 2", places=1, daily_item=day)


@pytest.fixture
def drug(db):
    return catalog.save_item(
        Item(
            kind=Kind.GOODS,
            name="Церукал",
            group=ItemGroup.objects.get(name="Препараты"),
            base_unit=Unit.objects.get(name="мл"),
        ),
        [{"unit": Unit.objects.get(name="мл"), "price": D("40")}],
    )


def test_admit_places_and_no_duplicates(pet, doctor, ward) -> None:
    h = services.admit(pet, ward, doctor, "Гастроэнтерит")
    other = clients.save_pet(
        Pet(owner=pet.owner, name="Мурка", species=pet.species, breed=pet.breed)
    )

    with pytest.raises(InpatientError, match="уже в стационаре"):
        services.admit(pet, ward, doctor)
    with pytest.raises(InpatientError, match="нет свободных мест"):
        services.admit(other, ward, doctor)
    assert h.client == pet.owner and services.days_count(h) == 1


def test_plan_creates_tasks_and_marks(pet, doctor, ward, drug) -> None:
    h = services.admit(pet, ward, doctor)
    today = timezone.localdate()

    plan = services.add_plan(
        h, "", ["20:00", "08:00"], today, days=3, item=drug, dose="0,3 мл", route="sc"
    )

    assert plan.title == "Церукал" and plan.times == ["08:00", "20:00"]
    assert plan.tasks.count() == 6
    task = services.sheet(h, today).first()
    services.mark_task(task, "done", doctor, quantity=D("0.3"))
    assert task.done_by == doctor and task.done_at
    with pytest.raises(InpatientError, match="почему пропущено"):
        services.mark_task(services.sheet(h, today).last(), "skipped", doctor)
    with pytest.raises(InpatientError, match="08:00"):
        services.add_plan(h, "Капельница", ["8 утра"], today)


def test_import_from_visit(pet, doctor, ward, drug) -> None:
    visit = medical.start_visit(pet, doctor)
    medical.save_prescriptions(
        visit,
        [{"item": drug, "dose": "0,3 мл", "route": "sc", "frequency": "2 раза в день", "days": 3}],
    )
    h = services.admit(pet, ward, doctor, visit=visit)

    assert services.import_from_visit(h) == 1
    plan = h.plans.get()
    assert plan.times == ["08:00", "20:00"] and plan.days == 3 and plan.route == "sc"


def test_observations_discharge_and_invoice(pet, doctor, ward, drug) -> None:
    h = services.admit(pet, ward, doctor)
    h.admitted_at = timezone.now() - timedelta(hours=30)  # вторые сутки
    h.save()
    plan = services.add_plan(
        h, "", ["00:00", "23:59"], timezone.localdate() - timedelta(days=1), days=3, item=drug
    )
    past = plan.tasks.filter(scheduled_at__lt=timezone.now()).first()
    services.mark_task(past, "done", doctor, quantity=D("0.5"))
    services.add_observation(h, doctor, temperature=D("38.9"), note="ест плохо")
    with pytest.raises(InpatientError, match="температуру"):
        services.add_observation(h, doctor, temperature=D("50"))

    services.discharge(h, "Выздоровление")
    invoice_id = services.create_invoice(h)

    assert h.status == "discharged" and services.days_count(h) == 2
    assert not plan.tasks.filter(
        status=TreatmentTask.Status.PLANNED, scheduled_at__gt=timezone.now()
    ).exists()
    from billing.models import Invoice

    lines = {
        line.item.name: line.quantity for line in Invoice.objects.get(pk=invoice_id).lines.all()
    }
    assert lines == {"Сутки стационара": D("2.000"), "Церукал": D("0.500")}
    with pytest.raises(InpatientError, match="выписан"):
        services.discharge(h)


def test_sheet_print(pet, doctor, ward) -> None:
    h = services.admit(pet, ward, doctor)
    services.add_plan(h, "Осмотр", ["09:00"], timezone.localdate())

    pdf = core.render_print(
        PrintTemplate.objects.get(kind="treatment_sheet"),
        services.sheet_context(h, timezone.localdate()),
    )

    assert pdf.startswith(b"%PDF")


def test_api_flow(pet, doctor, ward, drug) -> None:
    api = APIClient()
    api.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    today = timezone.localdate().isoformat()

    h = api.post(
        "/api/inpatient/hospitalizations/",
        {"pet": str(pet.pk), "ward": str(ward.pk), "doctor": str(doctor.pk), "reason": "Рвота"},
        format="json",
    ).json()
    plans = api.post(
        f"/api/inpatient/hospitalizations/{h['id']}/plans/",
        {"item": str(drug.pk), "times": ["08:00", "20:00"], "start_date": today, "days": 2},
        format="json",
    ).json()
    sheet = api.get(f"/api/inpatient/hospitalizations/{h['id']}/sheet/?date={today}").json()
    marked = api.post(
        f"/api/inpatient/hospitalizations/{h['id']}/tasks/{sheet[0]['id']}/mark/",
        {"status": "done"},
        format="json",
    ).json()
    obs = api.post(
        f"/api/inpatient/hospitalizations/{h['id']}/observations/",
        {"temperature": "38.5"},
        format="json",
    ).json()
    board = api.get("/api/inpatient/hospitalizations/").json()
    pdf = api.get(f"/api/inpatient/hospitalizations/{h['id']}/print-sheet/")
    full = api.post(
        "/api/inpatient/hospitalizations/",
        {"pet": str(pet.pk), "ward": str(ward.pk), "doctor": str(doctor.pk)},
        format="json",
    )

    assert plans[0]["title"] == "Церукал" and len(sheet) == 2
    assert marked["status"] == "done" and marked["done_by_name"]
    assert obs[0]["temperature"] == "38.5"
    assert (
        board[0]["tasks_today"]["done"] == 1
        and board[0]["last_observation"]["temperature"] == "38.5"
    )
    assert pdf["Content-Type"] == "application/pdf"
    assert "уже в стационаре" in full.json()["non_field_errors"][0]


def test_staff_and_my_tasks(pet, doctor, ward) -> None:

    assistant = get_user_model().objects.create_user(
        username="asst", password="x", last_name="Сидорова"
    )
    stranger = get_user_model().objects.create_user(username="other", password="x")
    h = services.admit(pet, ward, doctor, staff=[assistant])
    now = timezone.localtime()
    soon = (now + timedelta(minutes=10)).strftime("%H:%M")
    later = (now + timedelta(hours=3)).strftime("%H:%M") if now.hour < 20 else soon
    services.add_plan(h, "Церукал", [soon, later], now.date(), dose="0,3 мл")

    mine = list(services.my_tasks(assistant))

    assert list(h.staff.all()) == [assistant]
    assert [t.plan.title for t in mine] == ["Церукал"]  # только ближайшее — через 10 минут
    assert list(services.my_tasks(doctor)) == mine  # лечащий врач тоже получает
    assert list(services.my_tasks(stranger)) == []
    assert list(services.my_tasks(stranger, everyone=True)) == mine


def test_my_tasks_api_and_staff_names(pet, doctor, ward) -> None:
    assistant = get_user_model().objects.create_user(
        username="asst", password="x", last_name="Сидорова", first_name="Ольга"
    )
    api = APIClient()
    api.force_authenticate(assistant)
    admin = APIClient()
    admin.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    h = admin.post("/api/inpatient/hospitalizations/", {"pet": str(pet.pk), "ward": str(ward.pk), "doctor": str(doctor.pk),
                   "staff": [assistant.pk]}, format="json").json()  # fmt: skip
    now = timezone.localtime() - timedelta(minutes=5)
    admin.post(f"/api/inpatient/hospitalizations/{h['id']}/plans/", {"title": "Осмотр", "times": [now.strftime("%H:%M")],
               "start_date": now.date().isoformat()}, format="json")  # fmt: skip

    tasks = admin.get("/api/inpatient/hospitalizations/my-tasks/?all=1").json()
    assert h["staff_names"] == ["Сидорова О."]
    assert tasks[0]["pet_name"] == "Барсик" and tasks[0]["overdue"] is True
