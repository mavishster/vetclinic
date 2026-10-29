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
from medical.models import Diagnosis
from scheduling import services as scheduling
from scheduling.models import Appointment

URL = "/api/medical/visits/"


@pytest.fixture
def api(db):
    client = APIClient()
    client.force_authenticate(
        get_user_model().objects.create_superuser(username="a", password="x", last_name="Орлова")
    )
    return client


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


def test_create_edit_and_list_visits(api, pet) -> None:
    created = api.post(URL, {"pet": str(pet.pk)}, format="json").json()
    diagnosis = Diagnosis.objects.get(name="Цистит")

    updated = api.patch(
        f"{URL}{created['id']}/",
        {"weight": "4.5", "temperature": "38.9", "treatment_html": "<p>Осмотр</p>",
         "diagnoses": [{"diagnosis": str(diagnosis.pk), "kind": "preliminary"}]},
        format="json",
    )  # fmt: skip
    listed = api.get(f"{URL}?pet={pet.pk}").json()["results"]

    assert created["doctor_name"] == "Орлова"
    assert updated.status_code == 200
    assert updated.json()["diagnoses"][0]["name"] == "Цистит"
    assert [v["id"] for v in listed] == [created["id"]]


def test_from_appointment_vaccinate_and_print(api, pet) -> None:
    vaccine = catalog.save_item(
        Item(kind=Kind.GOODS, name="Нобивак DHPPi", group=ItemGroup.objects.get(name="Вакцины"), base_unit=Unit.objects.get(name="доза")),
        [{"unit": Unit.objects.get(name="доза"), "price": Decimal("900")}],
    )  # fmt: skip
    appointment = scheduling.save_appointment(
        Appointment(
            client=pet.owner,
            pet=pet,
            start=timezone.now(),
            end=timezone.now() + timedelta(minutes=20),
        ),
        force=True,
    )

    visit = api.post(
        f"{URL}from-appointment/", {"appointment": str(appointment.pk)}, format="json"
    ).json()
    vaccines = api.get("/api/medical/vaccines/").json()
    vaccinated = api.post(
        f"{URL}{visit['id']}/vaccinate/",
        {"vaccine": str(vaccine.pk), "next_date": str(timezone.localdate() + timedelta(days=21)), "repeat_at": "11:00"},
        format="json",
    )  # fmt: skip
    history = api.get(f"/api/medical/vaccinations/?pet={pet.pk}").json()
    removed = api.delete(f"{URL}{visit['id']}/vaccinations/{history[0]['id']}/")
    pdf = api.get(f"{URL}{visit['id']}/print/")

    assert visit["appointment_status"] == "in_progress"
    assert [v["name"] for v in vaccines] == ["Нобивак DHPPi"]
    assert vaccinated.status_code == 201
    assert vaccinated.json()["vaccinations"][0]["vaccine_name"] == "Нобивак DHPPi"
    assert removed.json()["vaccinations"] == []
    assert pdf["Content-Type"] == "application/pdf"


def test_permissions(db, pet) -> None:
    plain = APIClient()
    plain.force_authenticate(get_user_model().objects.create_user(username="u", password="x"))

    assert plain.get(URL).status_code == 403
    assert plain.post(URL, {"pet": str(pet.pk)}, format="json").status_code == 403
