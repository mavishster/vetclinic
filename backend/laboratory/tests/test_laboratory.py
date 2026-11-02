"""Лаборатория: приём результатов, отметки ↑↓, нераспределённые, привязка, динамика, API с ключом."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from clients import services as clients
from clients.models import Breed, Client, Pet, Species
from laboratory import services
from laboratory.models import Analyte, AnalyteNorm, LabResult
from medical import services as medical

D = Decimal
OAK = [
    {"code": "WBC", "value": "18.2", "unit": "10^9/L", "reference": "4.0-15.0", "flag": "H"},
    {"code": "RBC", "value": "7.1", "unit": "10^12/L", "reference": "5.5-8.5", "flag": ""},
    {"code": "GGT", "value": "<=5", "unit": "U/L", "reference": "<=10", "flag": ""},
    {
        "code": "NEWCODE",
        "name": "Новый показатель",
        "value": "3",
        "unit": "",
        "reference": "",
        "flag": "",
    },
]


@pytest.fixture
def visit(db):
    doctor = get_user_model().objects.create_user(username="doc", password="x")
    owner = clients.save_client(Client(last_name="Петров"))
    cats = Species.objects.get(name="Кошки")
    pet = clients.save_pet(
        Pet(
            owner=owner,
            name="Барсик",
            species=cats,
            breed=Breed.objects.get(name="Метис", species=cats),
        )
    )
    return medical.start_visit(pet, doctor)


def test_visit_gets_lab_code(visit) -> None:
    second = medical.start_visit(visit.pet, visit.doctor)

    assert visit.lab_code and second.lab_code == visit.lab_code + 1


def test_flags() -> None:
    assert services.flag_of("18.2", "4.0-15.0", "") == "high"
    assert services.flag_of("3,5", "4.0-15.0", "") == "low"
    assert services.flag_of("7", "5.5-8.5", "") == "normal"
    assert services.flag_of("7", "", "L") == "low"  # флаг прибора важнее
    assert services.flag_of("Positive", ">38 = Negative", "") == "positive"
    assert services.flag_of("<=5", "<=10", "") == ""  # референс не диапазон — без отметки


def test_ingest_to_visit_with_flags_and_new_analyte(visit) -> None:
    result = services.ingest(
        "Ozelle BHA-5000", "Общий анализ крови", str(visit.lab_code), OAK, message_id="abc"
    )

    values = {v.analyte.code: v for v in result.values.select_related("analyte")}
    assert result.visit == visit and result.pet == visit.pet and result.status == "assigned"
    assert values["WBC"].flag == "high" and values["WBC"].name == "Лейкоциты (WBC)"
    assert values["RBC"].flag == "normal" and values["RBC"].numeric == D("7.1")
    assert Analyte.objects.get(code="NEWCODE").name == "Новый показатель"
    assert (
        services.ingest("Ozelle BHA-5000", "ОАК", str(visit.lab_code), OAK, message_id="abc").pk
        == result.pk
    )  # повтор


def test_unknown_code_goes_to_unassigned_then_assign_uses_species_norm(visit) -> None:
    cats = visit.pet.species
    AnalyteNorm.objects.create(
        analyte=Analyte.objects.get(code="RBC"), species=cats, low=D("8"), high=D("10")
    )
    result = services.ingest(
        "Biochemistry",
        "Биохимия",
        "99999",
        [{"code": "RBC", "value": "7.1", "unit": "", "reference": ""}],
    )

    assert result.status == "unassigned" and result.pet is None
    services.assign(result, visit)

    assert result.status == "assigned" and result.values.get().flag == "low"  # норма кошек


def test_pet_lab_number_fallback(visit) -> None:
    pet = visit.pet
    pet.lab_number = "L-77"
    pet.save()

    result = services.ingest("Getein 1160", "ИФА", "L-77", [{"code": "fSAA", "value": "5"}])

    assert result.pet == pet and result.visit is None and result.status == "assigned"


def test_history(visit) -> None:
    services.ingest(
        "Bio",
        "Биохимия",
        str(visit.lab_code),
        [{"code": "CREA", "name": "Креатинин", "value": "120"}],
    )
    services.ingest(
        "Bio",
        "Биохимия",
        str(visit.lab_code),
        [{"code": "CREA", "name": "Креатинин", "value": "180"}],
    )

    rows = services.history(visit.pet, Analyte.objects.get(code="CREA"))

    assert [r["numeric"] for r in rows] == [D("120"), D("180")]


def test_ingest_api_needs_token(visit, settings) -> None:
    api = APIClient()
    body = {
        "device": "Ozelle",
        "analysis": "ОАК",
        "code": str(visit.lab_code),
        "message_id": "m1",
        "values": OAK,
    }

    settings.LAB_API_TOKEN = ""
    assert api.post("/api/laboratory/ingest/", body, format="json").status_code == 503
    settings.LAB_API_TOKEN = "secret"
    assert (
        api.post(
            "/api/laboratory/ingest/", body, format="json", HTTP_X_LAB_TOKEN="wrong"
        ).status_code
        == 403
    )
    ok = api.post("/api/laboratory/ingest/", body, format="json", HTTP_X_LAB_TOKEN="secret")

    assert ok.status_code == 201 and ok.json()["visit_lab_code"] == visit.lab_code
    assert LabResult.objects.count() == 1


def test_results_api_assign_and_history(visit) -> None:
    result = services.ingest(
        "Bio", "Биохимия", "000", [{"code": "CREA", "name": "Креатинин", "value": "150"}]
    )
    api = APIClient()
    api.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))

    unassigned = api.get("/api/laboratory/results/?status=unassigned").json()
    bad = api.post(
        f"/api/laboratory/results/{result.pk}/assign/", {"lab_code": "123456"}, format="json"
    )
    assigned = api.post(
        f"/api/laboratory/results/{result.pk}/assign/", {"lab_code": visit.lab_code}, format="json"
    ).json()
    history = api.get(
        f"/api/laboratory/results/history/?pet={visit.pet_id}&analyte={Analyte.objects.get(code='CREA').pk}"
    ).json()

    assert [r["id"] for r in unassigned] == [str(result.pk)]
    assert bad.status_code == 400
    assert assigned["visit_lab_code"] == visit.lab_code
    assert history[0]["numeric"] == "150.0000"
