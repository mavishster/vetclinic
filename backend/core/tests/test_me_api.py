import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        username="ivanov", password="secret-pass", last_name="Иванов", first_name="Иван"
    )


@pytest.fixture
def api(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_me_requires_login(db) -> None:
    assert APIClient().get("/api/core/me/").status_code == 403


def test_me_returns_name_pin_flag_and_permissions(api) -> None:
    data = api.get("/api/core/me/").json()

    assert data["short_name"] == "Иванов И."
    assert data["has_pin"] is False
    assert data["clinic"] == "Клиника"
    assert data["permissions"] == []


def test_set_pin_requires_correct_password(api) -> None:
    response = api.post("/api/core/me/pin/", {"password": "wrong", "pin": "2580"}, format="json")

    assert response.status_code == 400
    assert response.json() == {"password": ["Неверный пароль."]}


def test_set_pin_validates_pin(api) -> None:
    response = api.post(
        "/api/core/me/pin/", {"password": "secret-pass", "pin": "1234"}, format="json"
    )

    assert response.status_code == 400
    assert "слишком простой" in response.json()["pin"][0]


def test_set_pin(api, user) -> None:
    response = api.post(
        "/api/core/me/pin/", {"password": "secret-pass", "pin": "2580"}, format="json"
    )

    user.refresh_from_db()
    assert response.status_code == 200
    assert user.has_pin


def test_personal_ui_settings_are_saved_and_returned(db) -> None:
    from django.contrib.auth import get_user_model
    from rest_framework.test import APIClient

    user = get_user_model().objects.create_user(username="ui", password="x")
    api = APIClient()
    api.force_authenticate(user)

    saved = api.patch("/api/core/me/ui/", {"theme": "dark", "primary": "#6b4c9a"}, format="json")
    bad = api.patch("/api/core/me/ui/", {"primary": "red"}, format="json")
    me = api.get("/api/core/me/").json()

    assert saved.json() == {"theme": "dark", "primary": "#6b4c9a"}
    assert "#RRGGBB" in bad.json()["non_field_errors"][0]
    assert me["ui_settings"]["theme"] == "dark"
