"""QR-этикетка стационара: поля из настроек, лист А4 с вырезанием, права, проверка настроек."""

import base64

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from rest_framework.test import APIClient

from clients import services as clients
from clients.models import Breed, Client, Pet, Species
from core import services as core
from inpatient import qr, services
from inpatient.models import Ward

pytestmark = pytest.mark.django_db


@pytest.fixture
def doctor():
    return get_user_model().objects.create_user(username="doc", password="x", last_name="Иванова")


@pytest.fixture
def hosp(doctor):
    cats = Species.objects.get(name="Кошки")
    pet = clients.save_pet(
        Pet(
            owner=clients.save_client(Client(last_name="Петров")),
            name="Барсик",
            species=cats,
            breed=Breed.objects.get(name="Метис", species=cats),
        )
    )
    ward = Ward.objects.create(name="Палата 7", places=4)
    return services.admit(pet, ward, doctor, "Гастроэнтерит", place=2)


def admin_api():
    api = APIClient()
    api.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    return api


def test_label_has_selected_fields_in_order_and_skips_empty(hosp) -> None:
    label = qr.label_for(
        hosp, ["diagnosis", "pet_name", "weight", "nonsense", "ward_place"], "http://x"
    )

    # Порядок — как в настройках; пустой вес и убранное из системы поле не выводятся.
    assert [f["code"] for f in label["fields"]] == ["diagnosis", "pet_name", "ward_place"]
    assert label["fields"][0]["value"] == "Гастроэнтерит"
    assert label["fields"][2]["value"] == "Палата 7, место 2"
    assert "owner" not in {f["code"] for f in label["fields"]}


def test_qr_holds_only_card_url_no_patient_data(hosp) -> None:
    label = qr.label_for(hosp, ["pet_name"], "http://192.168.0.10/")

    assert label["url"] == f"http://192.168.0.10/inpatient/{hosp.pk}"
    svg = base64.b64decode(label["qr"].split(",", 1)[1]).decode()
    assert svg.startswith("<svg") and "Барсик" not in svg


def test_diagnosis_falls_back_to_visit_and_is_shortened(hosp, doctor) -> None:
    hosp.reason = "  длинный   диагноз " + "x" * 300
    assert len(qr.FIELDS["diagnosis"][1](hosp)) <= qr.DIAGNOSIS_LIMIT
    assert qr.FIELDS["diagnosis"][1](hosp).endswith("…")

    hosp.reason = ""
    hosp.visit = None
    assert qr.FIELDS["diagnosis"][1](hosp) == ""


def test_age_is_printed_from_birth_date(hosp) -> None:
    from datetime import date, timedelta

    hosp.pet.birth_date = date.today() - timedelta(days=400)
    hosp.pet.save()

    assert qr.FIELDS["age"][1](hosp).startswith("1 год")


def test_layout_95x140_gives_four_labels_per_a4() -> None:
    assert qr.layout(95, 140) == {"cols": 2, "rows": 2, "per_sheet": 4}
    assert qr.layout(200, 290)["per_sheet"] == 1  # не помещается — всё равно один на листе


def test_copies_are_split_into_sheets(hosp) -> None:
    context = qr.sheet_context([(hosp, 5)], "http://x")

    assert len(context["labels"]) == 5
    assert [len(s) for s in context["sheets"]] == [4, 1]


def test_pdf_endpoint_and_default_template(hosp) -> None:
    api = admin_api()

    response = api.get(f"/api/inpatient/hospitalizations/{hosp.pk}/qr-label/?copies=2")

    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    everyone = api.get("/api/inpatient/hospitalizations/qr-labels/")
    assert everyone.status_code == 200 and everyone.content.startswith(b"%PDF")


def test_print_needs_special_permission(hosp) -> None:
    user = get_user_model().objects.create_user(username="asst", password="x")
    role = Group.objects.create(name="Ассистент")
    role.permissions.add(Permission.objects.get(codename="view_hospitalization"))
    user.groups.add(role)
    api = APIClient()
    api.force_authenticate(user)

    denied = api.get(f"/api/inpatient/hospitalizations/{hosp.pk}/qr-label/")
    assert denied.status_code == 403 and "QR" in denied.json()["detail"]

    role.permissions.add(Permission.objects.get(codename="print_qr"))
    user = get_user_model().objects.get(pk=user.pk)  # права кэшируются у объекта
    api.force_authenticate(user)
    assert api.get(f"/api/inpatient/hospitalizations/{hosp.pk}/qr-label/").status_code == 200


def test_print_permission_is_listed_for_role_settings() -> None:
    assert "inpatient.print_qr" in core.special_permissions()


def test_default_template_renders_sample() -> None:
    from core.models import PrintTemplate

    template = PrintTemplate.objects.get(kind="hospitalization_qr")

    core.validate_print_template(template.kind, template.body)


def test_clinic_settings_are_validated_and_fields_listed() -> None:
    api = admin_api()
    url = "/api/core/clinic/"

    assert api.patch(url, {"qr_base_url": "192.168.0.10"}, format="json").status_code == 400
    assert api.patch(url, {"qr_size_mm": 5}, format="json").status_code == 400
    assert api.patch(url, {"qr_size_mm": 100}, format="json").status_code == 400  # шире этикетки
    ok = api.patch(
        url,
        {"qr_base_url": "http://192.168.0.10/", "qr_fields": ["pet_name", "age"]},
        format="json",
    )
    assert ok.status_code == 200 and ok.json()["qr_base_url"] == "http://192.168.0.10"
    codes = [f["code"] for f in api.get("/api/inpatient/qr-fields/").json()]
    assert codes[:3] == ["pet_name", "age", "diagnosis"] and "owner" in codes


def test_configured_base_url_is_used_when_given(hosp) -> None:
    clinic = core.current_clinic()
    clinic.qr_base_url = "https://vet.example.kg"
    clinic.save()

    context = qr.sheet_context([(hosp, 1)], "")

    assert context["labels"][0]["url"].startswith("https://vet.example.kg/inpatient/")
