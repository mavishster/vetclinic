import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from clients import services as clients
from clients.models import Client
from scheduling.models import Appointment, VisitPurpose

URL = "/api/scheduling/appointments/"


@pytest.fixture
def api(db):
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    return client


@pytest.fixture
def doctor(db):
    return get_user_model().objects.create_user(username="doc", password="x", last_name="Иванова")


def test_booking_with_quick_client_and_warning_flow(api, doctor) -> None:
    purpose = VisitPurpose.objects.get(name="Вакцинация")
    body = {
        "new_client": {"last_name": "Смирнова", "phone": "+7 912 000-11-22"},
        "doctor": str(doctor.pk), "purpose": str(purpose.pk), "pet_note": "кот",
        "start": "2026-11-02T10:00:00+03:00",
    }  # fmt: skip

    warned = api.post(URL, body, format="json")
    forced = api.post(f"{URL}?force=1", body, format="json")

    assert warned.status_code == 409
    assert warned.json()["warnings"] == ["Врач не в графике в это время."]
    assert forced.status_code == 201
    data = forced.json()
    assert data["client_name"] == "Смирнова"
    assert data["client_status"] == "temporary"
    assert data["end"].startswith("2026-11-02T10:20")  # длительность из цели — 20 мин
    assert (
        Client.objects.filter(last_name="Смирнова").count() == 1
    )  # после предупреждения клиент не создан


def test_status_endpoint_and_errors(api) -> None:
    client = clients.save_client(Client(last_name="Петров"))
    created = api.post(
        f"{URL}?force=1",
        {"client": str(client.pk), "start": "2026-11-02T10:00:00+03:00"},
        format="json",
    ).json()

    waiting = api.post(f"{URL}{created['id']}/status/", {"status": "waiting"}, format="json")
    bad = api.post(f"{URL}{created['id']}/status/", {"status": "completed"}, format="json")
    cancel = api.post(f"{URL}{created['id']}/status/", {"status": "cancelled"}, format="json")

    assert waiting.json()["status_label"] == "ожидает"
    assert "Нельзя перевести" in bad.json()["non_field_errors"][0]
    assert "причину" in cancel.json()["non_field_errors"][0]


def test_walk_in_and_calendar_day(api, doctor) -> None:
    client = clients.save_client(Client(last_name="Петров"))

    walk = api.post(
        f"{URL}walk-in/", {"client": str(client.pk), "doctor": str(doctor.pk)}, format="json"
    )
    day = walk.json()["start"][:10]
    calendar = api.get(f"/api/scheduling/calendar/?date={day}").json()

    assert walk.status_code == 201
    assert walk.json()["status"] == "waiting"
    assert [a["client_name"] for a in calendar["appointments"]] == ["Петров"]
    assert str(doctor.pk) in [d["id"] for d in calendar["doctors"]]


def test_filters_and_permissions(api, db) -> None:
    client = clients.save_client(Client(last_name="Петров"))
    api.post(
        f"{URL}?force=1",
        {"client": str(client.pk), "start": "2026-11-02T10:00:00+03:00"},
        format="json",
    )
    plain = APIClient()
    plain.force_authenticate(get_user_model().objects.create_user(username="u", password="x"))

    found = api.get(f"{URL}?from=2026-11-02&to=2026-11-02&client={client.pk}").json()
    other_day = api.get(f"{URL}?from=2026-11-03&to=2026-11-03").json()

    assert len(found) == 1 and other_day == []
    assert plain.get(URL).status_code == 403
    assert plain.get("/api/scheduling/calendar/").status_code == 403
    assert Appointment.objects.count() == 1
