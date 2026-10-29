import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from core import services


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        username="ivanov", password="secret-pass", last_name="Иванов", first_name="Иван"
    )


@pytest.fixture
def admin_api(db):
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    return client


def test_csrf_endpoint_sets_cookie(db) -> None:
    response = APIClient().get("/api/core/auth/csrf/")

    assert "csrftoken" in response.cookies


def test_login_and_logout_with_session(user) -> None:
    client = APIClient(enforce_csrf_checks=True)

    wrong = client.post(
        "/api/core/auth/login/", {"username": "ivanov", "password": "x"}, format="json"
    )
    ok = client.post(
        "/api/core/auth/login/", {"username": "ivanov", "password": "secret-pass"}, format="json"
    )
    me = client.get("/api/core/me/")

    assert wrong.status_code == 400
    assert wrong.json()["detail"] == "Неверный логин или пароль."
    assert ok.status_code == 200
    assert me.json()["short_name"] == "Иванов И."

    client.get("/api/core/auth/csrf/")
    token = client.cookies["csrftoken"].value
    assert client.post("/api/core/auth/logout/", HTTP_X_CSRFTOKEN=token).status_code == 200
    assert client.get("/api/core/me/").status_code == 403


def test_inactive_user_cannot_log_in(user) -> None:
    user.is_active = False
    user.save()

    response = APIClient().post(
        "/api/core/auth/login/", {"username": "ivanov", "password": "secret-pass"}, format="json"
    )

    assert response.status_code == 400


def test_matrix_lists_modules_with_entities(admin_api) -> None:
    data = admin_api.get("/api/core/roles/matrix/").json()

    codes = [m["code"] for m in data["modules"]]
    assert codes[:2] == ["core", "clients"]
    assert "testapp" not in codes
    entities = [e["code"] for e in data["modules"][1]["entities"]]
    assert entities[:2] == ["clients.client", "clients.pet"]
    assert "clients.clientphone" not in entities
    assert [a["code"] for a in data["actions"]] == ["view", "edit", "delete"]


def test_create_role_with_matrix_and_users(admin_api, user) -> None:
    response = admin_api.post(
        "/api/core/roles/",
        {
            "name": "Регистратор",
            "users": [str(user.pk)],
            "access": {"clients.species": ["view", "edit"], "core.printtemplate": ["view"]},
        },
        format="json",
    )

    assert response.status_code == 201
    role = Group.objects.get(name="Регистратор")
    assert services.entity_actions(role, "clients.species") == {"view", "edit"}
    assert user.has_perm("clients.change_species")
    assert user.has_perm("core.view_printtemplate")
    assert not user.has_perm("clients.view_breed")
    permissions = response.json()["access"]
    assert permissions["clients.species"] == ["edit", "view"]
    assert permissions["clients.breed"] == []


def test_update_role_replaces_actions_of_listed_entities_only(admin_api) -> None:
    role = Group.objects.create(name="Врач")
    services.set_module_permissions(role, "clients", {"view", "edit", "delete"})

    admin_api.patch(
        f"/api/core/roles/{role.pk}/",
        {"access": {"clients.species": ["view"]}},
        format="json",
    )

    assert services.entity_actions(role, "clients.species") == {"view"}
    assert services.entity_actions(role, "clients.breed") == {"view", "edit", "delete"}


def test_role_management_can_be_granted(admin_api, user) -> None:
    role = Group.objects.create(name="Старший администратор")
    services.set_entity_permissions(role, "auth.group", {"view", "edit"})
    user.groups.add(role)
    client = APIClient()
    client.force_authenticate(user)

    assert client.get("/api/core/roles/").status_code == 200


def test_unknown_entity_is_rejected_by_api(admin_api) -> None:
    response = admin_api.post(
        "/api/core/roles/", {"name": "X", "access": {"rocket.engine": ["view"]}}, format="json"
    )

    assert response.status_code == 400


def test_roles_require_permissions(user) -> None:
    client = APIClient()
    client.force_authenticate(user)

    assert client.get("/api/core/roles/").status_code == 403
    assert client.get("/api/core/users/").status_code == 403


def test_users_list_shows_active_only(admin_api, user) -> None:
    get_user_model().objects.create_user(username="gone", password="x", is_active=False)

    usernames = [u["username"] for u in admin_api.get("/api/core/users/").json()]

    assert "ivanov" in usernames
    assert "gone" not in usernames
