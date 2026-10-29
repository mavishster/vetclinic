"""Записи на приём: правила, предупреждения, статусы, быстрая запись, выборки."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from clients import services as clients
from clients.models import Breed, Client, Pet, Species
from scheduling import services
from scheduling.models import Appointment, VisitPurpose
from scheduling.services import AppointmentError, AppointmentWarning
from staff import services as staff
from staff.models import IntervalType, WorkInterval

MSK = ZoneInfo("Europe/Moscow")
S = Appointment.Status


def at(hour: int, minute: int = 0, day: int = 2) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=MSK)


@pytest.fixture
def doctor(db):
    user = get_user_model().objects.create_user(username="doc", password="x", last_name="Иванова")
    staff.save_interval(
        WorkInterval(
            user=user, start=at(9), end=at(21), interval_type=IntervalType.objects.get(name="Приём")
        )
    )
    return user


@pytest.fixture
def client_(db):
    return clients.save_client(Client(last_name="Петров"), [{"number": "+7 900 111-22-33"}])


@pytest.fixture
def pet(client_):
    cats = Species.objects.get(name="Кошки")
    return clients.save_pet(
        Pet(
            owner=client_,
            name="Барсик",
            species=cats,
            breed=Breed.objects.get(name="Метис", species=cats),
        )
    )


def book(client, doctor=None, start=None, end=None, force=False, **fields):
    start = start or at(10)
    appointment = Appointment(
        client=client,
        doctor=doctor,
        start=start,
        end=end or start + timedelta(minutes=30),
        **fields,
    )
    return services.save_appointment(appointment, force=force)


def test_simple_booking_without_warnings(doctor, client_, pet) -> None:
    appointment = book(client_, doctor, pet=pet, purpose=VisitPurpose.objects.get(name="Первичный"))

    assert appointment.status == S.PLANNED
    assert appointment.clinic.name == "Клиника"


def test_end_after_start_and_pet_of_this_client(doctor, client_, pet) -> None:
    other = clients.save_client(Client(last_name="Сидоров"))

    with pytest.raises(AppointmentError, match="позже начала"):
        book(client_, doctor, start=at(10), end=at(10))
    with pytest.raises(AppointmentError, match="другому клиенту"):
        book(other, doctor, pet=pet)


def test_warnings_busy_off_shift_and_same_day(doctor, client_) -> None:
    book(client_, doctor, start=at(10))
    other = clients.save_client(Client(last_name="Сидоров"))

    with pytest.raises(AppointmentWarning) as busy:
        book(other, doctor, start=at(10, 15))
    with pytest.raises(AppointmentWarning) as off_shift:
        book(other, doctor, start=at(22))
    with pytest.raises(AppointmentWarning) as same_day:
        book(client_, None, start=at(15))

    assert "уже занят: 10:00–10:30, Петров" in busy.value.warnings[0]
    assert off_shift.value.warnings == ["Врач не в графике в это время."]
    assert same_day.value.warnings == ["Клиент уже записан на этот день: 10:00."]
    assert book(other, doctor, start=at(10, 15), force=True).pk  # «записать всё равно»


def test_cancelled_appointment_does_not_block(doctor, client_) -> None:
    first = book(client_, doctor, start=at(10))
    services.change_status(first, S.CANCELLED, "Перенёс")

    other = clients.save_client(Client(last_name="Сидоров"))
    assert book(other, doctor, start=at(10)).pk


def test_status_flow_with_timestamps(doctor, client_) -> None:
    appointment = book(client_, doctor)

    services.change_status(appointment, S.WAITING)
    services.change_status(appointment, S.IN_PROGRESS)
    services.change_status(appointment, S.COMPLETED)

    assert appointment.arrived_at and appointment.started_at and appointment.completed_at
    with pytest.raises(AppointmentError, match="Нельзя перевести"):
        services.change_status(appointment, S.CANCELLED)


def test_cancel_needs_reason_and_can_be_restored(doctor, client_) -> None:
    appointment = book(client_, doctor)

    with pytest.raises(AppointmentError, match="причину"):
        services.change_status(appointment, S.CANCELLED)
    services.change_status(appointment, S.CANCELLED, "Заболел хозяин")
    services.change_status(appointment, S.PLANNED)

    assert appointment.cancel_reason == ""


def test_overdue_is_highlight_not_status(doctor, client_) -> None:
    appointment = book(client_, doctor, start=at(10))

    assert services.is_overdue(appointment, now=at(10, 45))
    assert not services.is_overdue(appointment, now=at(10, 15))
    services.change_status(appointment, S.WAITING)
    assert not services.is_overdue(appointment, now=at(12))


def test_quick_temporary_client_and_walk_in(doctor) -> None:
    client = services.quick_client("Смирнова", "Ольга", "8 912 000 11 22")
    appointment = services.walk_in(Appointment(client=client, doctor=doctor, pet_note="кот Пушок"))

    assert client.status == Client.Status.TEMPORARY
    assert client.phones.get().number == "8 912 000 11 22"
    assert appointment.status == S.WAITING
    assert appointment.source == Appointment.Source.WALK_IN
    assert appointment.end - appointment.start == timedelta(minutes=30)


def test_active_for_pet_prefers_in_progress(doctor, client_, pet) -> None:
    today = timezone.localdate()
    morning = datetime.combine(today, datetime.min.time(), MSK) + timedelta(hours=9)
    planned = book(client_, doctor, pet=pet, start=morning, force=True)
    current = book(client_, None, pet=pet, start=morning + timedelta(hours=2), force=True)
    services.change_status(current, S.IN_PROGRESS)

    assert services.active_for(pet) == current
    services.change_status(current, S.COMPLETED)
    assert services.active_for(pet) == planned
