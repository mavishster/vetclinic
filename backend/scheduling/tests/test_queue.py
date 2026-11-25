"""Электронная очередь: номера, приглашение в кабинет, экран в холле."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.utils import timezone
from rest_framework.test import APIClient

from clients import services as clients
from clients.models import Client
from core import services as core
from scheduling import services
from scheduling.models import Appointment, Room

S = Appointment.Status
URL = "/api/scheduling/appointments/"


@pytest.fixture
def doctor(db):
    return get_user_model().objects.create_user(
        username="doc", password="x", last_name="Асанова", first_name="Айгуль"
    )


@pytest.fixture
def other_doctor(db):
    return get_user_model().objects.create_user(username="doc2", password="x", last_name="Исаев")


@pytest.fixture
def rooms(db):
    return Room.objects.create(name="Кабинет 1"), Room.objects.create(name="Кабинет 2")


def book(last_name: str, doctor=None, minutes: int = 0, pet_note: str = "") -> Appointment:
    client = clients.save_client(Client(last_name=last_name))
    start = timezone.now() + timedelta(minutes=minutes)
    appointment = Appointment(
        client=client, doctor=doctor, start=start, end=start + timedelta(minutes=30),
        pet_note=pet_note,
    )  # fmt: skip
    return services.save_appointment(appointment, force=True)


def arrive(appointment: Appointment) -> Appointment:
    return services.change_status(appointment, S.WAITING)


# --- Номера ---------------------------------------------------------------------------


def test_numbers_go_in_order_of_arrival_including_walk_ins(db) -> None:
    first, second = book("Петров"), book("Смирнова")
    walk = Appointment(client=clients.save_client(Client(last_name="Ким")))

    arrive(second)
    arrive(first)
    services.walk_in(walk)

    assert (second.queue_number, first.queue_number, walk.queue_number) == (1, 2, 3)
    assert walk.queue_date == timezone.localdate()


def test_number_is_kept_when_status_goes_back_and_forth_the_same_day(db) -> None:
    appointment = arrive(book("Петров"))
    arrive(book("Смирнова"))

    services.change_status(appointment, S.PLANNED)
    arrive(appointment)

    assert appointment.queue_number == 1


def test_numbers_start_from_one_every_day(db) -> None:
    yesterday = arrive(book("Петров"))
    Appointment.objects.filter(pk=yesterday.pk).update(
        queue_date=timezone.localdate() - timedelta(days=1)
    )

    today = arrive(book("Смирнова"))

    assert today.queue_number == 1


def test_number_of_a_deleted_appointment_is_not_given_again(db) -> None:
    deleted = arrive(book("Петров"))
    deleted.delete()

    assert arrive(book("Смирнова")).queue_number == 2


def test_planned_patient_taken_straight_to_doctor_gets_no_number(db) -> None:
    appointment = services.change_status(book("Петров"), S.IN_PROGRESS)

    assert appointment.queue_number is None


# --- Приглашение ----------------------------------------------------------------------


def test_invite_only_waiting(rooms, doctor) -> None:
    appointment = book("Петров", doctor)

    with pytest.raises(services.AppointmentError, match="только того, кто ожидает"):
        services.invite(appointment, doctor, rooms[0])


def test_first_invite_asks_for_room_then_room_is_remembered_for_the_doctor(
    rooms, doctor, other_doctor
) -> None:
    first, second = arrive(book("Петров", doctor)), arrive(book("Смирнова", doctor))
    foreign = arrive(book("Ким", other_doctor))

    with pytest.raises(services.RoomRequired):
        services.invite(first, doctor)
    services.invite(first, doctor, rooms[1])
    services.invite(second, doctor)

    assert second.room == rooms[1]
    assert services.suggested_room(foreign, other_doctor) is None


def test_any_doctor_appointment_remembers_room_of_who_invites(rooms, doctor) -> None:
    first, second = arrive(book("Петров")), arrive(book("Смирнова"))

    services.invite(first, doctor, rooms[0])

    assert services.suggested_room(second, doctor) == rooms[0]


def test_invite_without_any_rooms_explains_what_to_do(db, doctor) -> None:
    appointment = arrive(book("Петров", doctor))

    with pytest.raises(services.AppointmentError, match="Справочники → Кабинеты"):
        services.invite(appointment, doctor)


def test_inactive_room_is_neither_offered_nor_accepted(rooms, doctor) -> None:
    first, second = arrive(book("Петров", doctor)), arrive(book("Смирнова", doctor))
    services.invite(first, doctor, rooms[0])
    rooms[0].is_active = False
    rooms[0].save()

    assert services.suggested_room(second, doctor) is None
    with pytest.raises(services.AppointmentError, match="выключен"):
        services.invite(second, doctor, rooms[0])


def test_invite_again_announces_again(rooms, doctor) -> None:
    appointment = arrive(book("Петров", doctor))
    services.invite(appointment, doctor, rooms[0])
    first_call = appointment.called_at

    services.invite(appointment, doctor)

    assert appointment.called_at > first_call
    assert appointment.room == rooms[0]


def test_going_back_clears_the_invitation(rooms, doctor) -> None:
    appointment = arrive(book("Петров", doctor))
    services.invite(appointment, doctor, rooms[0])

    services.change_status(appointment, S.PLANNED)

    assert (appointment.called_at, appointment.room, appointment.called_by) == (None, None, None)


# --- Экран в холле --------------------------------------------------------------------


def test_board_waiting_order_by_appointment_time_or_arrival(db) -> None:
    on_time = arrive(book("Вовремя", minutes=30))  # пришёл заранее — ждёт своего времени
    late = arrive(book("Опоздал", minutes=-40))  # пришёл позже своего времени
    walk = services.walk_in(Appointment(client=clients.save_client(Client(last_name="Без"))))

    waiting = services.queue_board()["waiting"]

    assert [a.pk for a in waiting] == [late.pk, walk.pk, on_time.pk]


def test_board_moves_invited_to_called_and_hides_them_after_a_while(rooms, doctor) -> None:
    invited, waiting = arrive(book("Петров", doctor)), arrive(book("Смирнова", doctor))
    services.invite(invited, doctor, rooms[0])
    later = timezone.now() + timedelta(minutes=services.CALLED_SHOW_MINUTES + 1)

    board = services.queue_board()

    assert [a.pk for a in board["called"]] == [invited.pk]
    assert [a.pk for a in board["waiting"]] == [waiting.pk]
    assert services.queue_board(later)["called"] == []


def test_started_appointment_stays_on_board_briefly(rooms, doctor) -> None:
    appointment = arrive(book("Петров", doctor))
    services.invite(appointment, doctor, rooms[0])
    services.change_status(appointment, S.IN_PROGRESS)
    later = timezone.now() + timedelta(minutes=services.STARTED_SHOW_MINUTES + 1)

    assert [a.pk for a in services.queue_board()["called"]] == [appointment.pk]
    assert services.queue_board(later)["called"] == []


def test_cancelled_and_completed_are_not_on_board(rooms, doctor) -> None:
    cancelled = arrive(book("Петров", doctor))
    services.change_status(cancelled, S.CANCELLED, "передумал")

    board = services.queue_board()

    assert board == {"called": [], "waiting": []}


# --- API ------------------------------------------------------------------------------


@pytest.fixture
def api(doctor):
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    return client


def test_api_invite_asks_for_room_and_offers_list(api, rooms, doctor) -> None:
    appointment = arrive(book("Петров", doctor))

    asked = api.post(f"{URL}{appointment.pk}/invite/", {}, format="json")
    options = api.get(f"{URL}{appointment.pk}/invite/").json()
    invited = api.post(f"{URL}{appointment.pk}/invite/", {"room": str(rooms[1].pk)}, format="json")

    assert asked.status_code == 400 and "room" in asked.json()
    assert [r["name"] for r in options["rooms"]] == ["Кабинет 1", "Кабинет 2"]
    assert options["suggested"] is None
    assert invited.status_code == 200
    assert invited.json()["room_name"] == "Кабинет 2"
    assert invited.json()["queue_number"] == 1


def test_api_invite_rejects_unknown_room(api, rooms, doctor) -> None:
    appointment = arrive(book("Петров", doctor))
    rooms[0].delete()

    answer = api.post(f"{URL}{appointment.pk}/invite/", {"room": str(rooms[0].pk)}, format="json")

    assert answer.status_code == 400


def test_screen_account_sees_only_board_without_personal_data(rooms, doctor) -> None:
    appointment = arrive(book("Смирнова", doctor, pet_note="кот Мурзик"))
    services.invite(appointment, doctor, rooms[0])
    screen = get_user_model().objects.create_user(username="tv", password="x")
    role = Group.objects.create(name="Экран")
    role.permissions.add(Permission.objects.get(codename="queue_screen"))
    screen.groups.add(role)
    api = APIClient()
    api.force_authenticate(screen)

    board = api.get("/api/scheduling/queue/")
    appointments = api.get(URL)

    assert board.status_code == 200
    assert board.json()["called"][0] == {
        "id": str(appointment.pk), "number": 1, "pet": "кот Мурзик", "doctor": "Асанова А.",
        "room": "Кабинет 1", "called_at": board.json()["called"][0]["called_at"],
    }  # fmt: skip
    assert "Смирнова" not in board.content.decode()
    assert appointments.status_code == 403


def test_board_closed_without_rights(db) -> None:
    api = APIClient()
    api.force_authenticate(get_user_model().objects.create_user(username="x", password="x"))

    assert api.get("/api/scheduling/queue/").status_code == 403


def test_manager_template_does_not_turn_staff_into_a_screen(db) -> None:
    templates = {t["code"]: t for t in core.role_templates()}

    assert "scheduling.queue_screen" not in templates["manager"]["special"]
    assert templates["queue_screen"]["special"] == ["scheduling.queue_screen"]
    assert templates["queue_screen"]["access"] == {}
