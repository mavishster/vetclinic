"""Экран «у клетки»: данные карточки, доступ по ролям, выписанный пациент."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from clients import services as clients
from clients.models import Breed, Client, Pet, Species
from core import services as core
from inpatient import services
from inpatient.models import TreatmentTask, Ward

pytestmark = pytest.mark.django_db


@pytest.fixture
def doctor():
    return get_user_model().objects.create_user(username="doc", password="x", last_name="Иванова")


@pytest.fixture
def hosp(doctor):
    cats = Species.objects.get(name="Кошки")
    owner = clients.save_client(
        Client(last_name="Петров"), phones=[{"number": "+996555123456", "is_primary": True}]
    )
    pet = clients.save_pet(
        Pet(
            owner=owner,
            name="Барсик",
            species=cats,
            breed=Breed.objects.get(name="Метис", species=cats),
        )
    )
    return services.admit(pet, Ward.objects.create(name="Палата 7", places=4), doctor, "Гастрит")


def _api(*grants: tuple[str, set[str]]) -> APIClient:
    role = Group.objects.create(name=f"role{Group.objects.count()}")
    for entity, actions in grants:
        core.set_entity_permissions(role, entity, actions)
    user = get_user_model().objects.create_user(username=f"u{role.pk}", password="x")
    user.groups.add(role)
    api = APIClient()
    api.force_authenticate(user)
    return api


def _url(h) -> str:
    return f"/api/inpatient/hospitalizations/{h.pk}/"


def test_card_has_age_diagnosis_and_phone_only_with_clients_right(hosp) -> None:
    with_clients = _api(("inpatient.hospitalization", {"view"}), ("clients.client", {"view"}))
    without = _api(("inpatient.hospitalization", {"view"}))

    card = with_clients.get(_url(hosp)).json()["cage"]
    plain = without.get(_url(hosp)).json()["cage"]

    assert card["diagnosis"] == "Гастрит" and card["species_breed"].startswith("Кошки")
    assert card["owner_phone"] == "+996555123456"
    assert plain["owner_phone"] == ""


def test_list_does_not_carry_cage_data(hosp) -> None:
    api = _api(("inpatient.hospitalization", {"view"}), ("clients.client", {"view"}))

    row = api.get("/api/inpatient/hospitalizations/").json()
    row = (row["results"] if isinstance(row, dict) else row)[0]

    assert row["cage"] is None


def test_no_right_means_no_data(hosp) -> None:
    api = _api(("clients.client", {"view"}))

    response = api.get(_url(hosp))

    assert response.status_code == 403
    assert "Барсик" not in response.content.decode()


def test_view_only_role_sees_sheet_but_cannot_mark(hosp) -> None:
    services.add_plan(hosp, "Осмотр", ["08:00"], services.timezone.localdate())
    task = TreatmentTask.objects.get()
    viewer = _api(("inpatient.hospitalization", {"view"}))
    nurse = _api(("inpatient.hospitalization", {"view", "edit"}))

    assert viewer.get(f"{_url(hosp)}sheet/").status_code == 200
    assert viewer.post(f"{_url(hosp)}tasks/{task.pk}/mark/", {"status": "done"}).status_code == 403
    assert nurse.post(f"{_url(hosp)}tasks/{task.pk}/mark/", {"status": "done"}).status_code == 200


def test_discharged_patient_sheet_is_closed(hosp, doctor) -> None:
    services.add_plan(hosp, "Осмотр", ["00:00"], services.timezone.localdate())
    task = TreatmentTask.objects.get()
    services.discharge(hosp, "Выздоровел")
    nurse = _api(("inpatient.hospitalization", {"view", "edit"}))

    marked = nurse.post(f"{_url(hosp)}tasks/{task.pk}/mark/", {"status": "done"})
    note = nurse.post(f"{_url(hosp)}observations/", {"note": "бодр"}, format="json")

    assert marked.status_code == 400 and note.status_code == 400
    assert nurse.get(_url(hosp)).json()["outcome"] == "Выздоровел"
