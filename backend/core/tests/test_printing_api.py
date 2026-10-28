import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import PrintTemplate

URL = "/api/core/print-templates/"


@pytest.fixture
def api(db):
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    return client


def test_requires_permissions(db) -> None:
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_user(username="u", password="x"))

    assert client.get(URL).status_code == 403


def test_kinds_list_variables_and_filters(api) -> None:
    data = api.get(f"{URL}kinds/").json()

    general = next(kind for kind in data["kinds"] if kind["code"] == "general")
    assert general["title"] == "Общий документ"
    assert "clinic.name" in general["variables"]
    assert "money" in data["filters"]


def test_preview_returns_html_with_sample_data(api) -> None:
    response = api.post(
        f"{URL}preview/", {"kind": "general", "body": "<b>{{ clinic.name }}</b>"}, format="json"
    )

    assert response.status_code == 200
    assert "<b>Клиника</b>" in response.json()["html"]


def test_preview_reports_template_error(api) -> None:
    response = api.post(f"{URL}preview/", {"kind": "general", "body": "{{ x "}, format="json")

    assert response.status_code == 400
    assert "Ошибка в шаблоне" in response.json()["body"][0]


def test_create_validates_body(api) -> None:
    bad = api.post(URL, {"kind": "general", "name": "Б", "body": "{% for %}"}, format="json")
    good = api.post(URL, {"kind": "general", "name": "Памятка", "body": "<p>ok</p>"}, format="json")

    assert bad.status_code == 400
    assert good.status_code == 201


def test_sample_pdf_of_saved_template(api) -> None:
    template = PrintTemplate.objects.get(kind="general")

    response = api.get(f"{URL}{template.pk}/sample/")

    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_admin_form_shows_template_error_and_preview_action(client, db) -> None:
    client.force_login(get_user_model().objects.create_superuser(username="adm", password="x"))
    add_url = reverse("admin:core_printtemplate_add")

    page = client.get(add_url)
    invalid = client.post(
        add_url, {"kind": "general", "name": "Сломанная", "is_active": "on", "body": "{% if %}"}
    )
    preview = client.post(
        reverse("admin:core_printtemplate_changelist"),
        {
            "action": "preview_pdf",
            "_selected_action": [str(PrintTemplate.objects.get(kind="general").pk)],
        },
    )

    assert page.status_code == 200
    assert "Ошибка в шаблоне" in invalid.content.decode()
    assert preview["Content-Type"] == "application/pdf"
