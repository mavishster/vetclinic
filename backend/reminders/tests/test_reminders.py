"""Напоминания: сбор из профилактики, записей и повторных приёмов; автозакрытие; обзвон."""

from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from clients import services as clients
from clients.models import Breed, Client, Pet, Species
from medical import services as medical
from medical.models import PreventionType
from reminders import services
from reminders.models import Reminder
from scheduling import services as scheduling
from scheduling.models import Appointment

D = Decimal
S = Reminder.Status


@pytest.fixture
def doctor(db):
    return get_user_model().objects.create_user(username="doc", password="x", last_name="Иванова")


@pytest.fixture
def pet(db):
    owner = clients.save_client(Client(last_name="Петров"), [{"number": "+7 900 111-22-33"}])
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
def vaccine(db):
    return catalog.save_item(
        Item(
            kind=Kind.GOODS,
            name="Нобивак Rabies",
            group=ItemGroup.objects.get(name="Вакцины"),
            base_unit=Unit.objects.get(name="доза"),
        ),
        [{"unit": Unit.objects.get(name="доза"), "price": D("700")}],
    )


def vaccinate(pet, doctor, vaccine, in_days):
    visit = medical.start_visit(pet, doctor)
    return medical.add_prevention(visit, PreventionType.objects.get(kind="vaccination"), vaccine,
                                  next_date=timezone.localdate() + timedelta(days=in_days))  # fmt: skip


def test_prevention_due_soon_becomes_reminder_once(pet, doctor, vaccine) -> None:
    vaccinate(pet, doctor, vaccine, in_days=5)
    vaccinate(
        pet.__class__.objects.get(pk=pet.pk), doctor, vaccine, in_days=5
    )  # вторая закрывает первую

    services.refresh()
    services.refresh()  # повторный сбор — без дублей

    reminders = list(Reminder.objects.filter(kind="prevention"))
    open_ = [r for r in reminders if r.status == S.OPEN]
    assert len(open_) == 1
    assert "Вакцинация: Нобивак Rabies — срок" in open_[0].text


def test_far_prevention_not_yet(pet, doctor, vaccine) -> None:
    vaccinate(pet, doctor, vaccine, in_days=40)

    services.refresh()

    assert not Reminder.objects.exists()


def test_new_procedure_makes_reminder_obsolete(pet, doctor, vaccine) -> None:
    vaccinate(pet, doctor, vaccine, in_days=3)
    services.refresh()

    vaccinate(pet, doctor, vaccine, in_days=365)  # сделали — прежний срок закрыт
    services.refresh()

    assert Reminder.objects.get().status == S.OBSOLETE  # новый срок через год — ещё не в списке


def test_appointment_tomorrow_and_cancelled(pet, doctor) -> None:
    zone = timezone.get_current_timezone()
    start = datetime.combine(timezone.localdate() + timedelta(days=1), time(10, 30), zone)
    appointment = scheduling.save_appointment(
        Appointment(
            client=pet.owner, pet=pet, doctor=doctor, start=start, end=start + timedelta(minutes=30)
        ),
        force=True,
    )

    services.refresh()
    reminder = Reminder.objects.get(kind="appointment")
    assert reminder.text.startswith("Приём ") and "10:30" in reminder.text

    scheduling.change_status(appointment, "cancelled", "Передумал")
    services.refresh()
    reminder.refresh_from_db()
    assert reminder.status == S.OBSOLETE


def test_revisit_and_booking_closes_it(pet, doctor) -> None:
    visit = medical.start_visit(pet, doctor)
    visit.next_visit_date = timezone.localdate() + timedelta(days=2)
    medical.save_visit(visit)
    services.refresh()
    reminder = Reminder.objects.get(kind="revisit")

    start = timezone.now() + timedelta(days=2)
    scheduling.save_appointment(
        Appointment(client=pet.owner, pet=pet, start=start, end=start + timedelta(minutes=20)),
        force=True,
    )
    services.refresh()

    reminder.refresh_from_db()
    assert reminder.status == S.BOOKED


def test_call_outcomes(pet, doctor, vaccine) -> None:
    vaccinate(pet, doctor, vaccine, in_days=2)
    services.refresh()
    reminder = Reminder.objects.get()

    services.mark(reminder, S.NO_ANSWER, doctor)
    services.mark(reminder, S.NO_ANSWER, doctor)
    assert reminder.attempts == 2 and reminder in services.to_call()

    services.mark(reminder, S.DONE, doctor, "Придут в субботу")
    assert reminder not in services.to_call()
    assert reminder.note == "Придут в субботу" and reminder.contacted_by == doctor
    with pytest.raises(services.ReminderError):
        services.mark(reminder, "fly", doctor)


def test_api_list_mark_and_client_history(pet, doctor, vaccine) -> None:
    vaccinate(pet, doctor, vaccine, in_days=1)
    api = APIClient()
    api.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))

    listed = api.get("/api/reminders/reminders/").json()
    marked = api.post(
        f"/api/reminders/reminders/{listed[0]['id']}/mark/", {"status": "done"}, format="json"
    ).json()
    history = api.get(f"/api/reminders/reminders/?client={pet.owner_id}").json()
    count = api.get("/api/reminders/reminders/count/").json()

    assert listed[0]["phone"] == "+7 900 111-22-33" and listed[0]["pet_name"] == "Барсик"
    assert marked["status_label"] == "напомнили"
    assert history[0]["status"] == "done"
    assert count == {"to_call": 0}
