import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from core import services as core
from staff.models import IntervalTemplate, IntervalType, Position

URL = "/api/staff/employees/"


@pytest.fixture
def admin_api(db):
    api = APIClient()
    api.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    return api


def client_with(entity_actions: dict[str, set[str]]) -> APIClient:
    role = Group.objects.create(name="Роль")
    for entity, actions in entity_actions.items():
        core.set_entity_permissions(role, entity, actions)
    user = get_user_model().objects.create_user(username="hr", password="x")
    user.groups.add(role)
    api = APIClient()
    api.force_authenticate(user)
    return api


def new_employee(api, **extra):
    return api.post(
        URL,
        {"username": "ivanova", "last_name": "Иванова", "first_name": "Анна", "password": "Vet-clinic-2026",
         "position": str(Position.objects.get(name="Врач").pk), **extra},
        format="json",
    )  # fmt: skip


def test_create_employee_with_account_and_roles(admin_api) -> None:
    role = Group.objects.create(name="Врач")

    response = new_employee(admin_api, roles=[role.pk])

    assert response.status_code == 201
    user = get_user_model().objects.get(username="ivanova")
    assert user.check_password("Vet-clinic-2026")
    assert list(user.groups.all()) == [role]
    assert response.json()["position_name"] == "Врач"
    assert response.json()["full_name"] == "Иванова Анна"


def test_account_validation(admin_api) -> None:
    new_employee(admin_api)

    taken = new_employee(admin_api)
    weak = admin_api.post(
        URL, {"username": "x2", "last_name": "Х", "password": "123"}, format="json"
    )
    no_password = admin_api.post(URL, {"username": "x3", "last_name": "Х"}, format="json")

    assert "занят" in taken.json()["non_field_errors"][0]
    assert weak.status_code == 400
    assert "пароль" in no_password.json()["non_field_errors"][0].lower()


def test_roles_can_be_assigned_only_by_role_managers(db) -> None:
    role = Group.objects.create(name="Админы")
    hr = client_with({"staff.employee": {"view", "edit"}})

    denied = new_employee(hr, roles=[role.pk])
    allowed = new_employee(hr)

    assert denied.status_code == 400
    assert "роли" in denied.json()["roles"][0]
    assert allowed.status_code == 201


def test_delete_deactivates_account(admin_api) -> None:
    employee_id = new_employee(admin_api).json()["id"]

    admin_api.delete(f"{URL}{employee_id}/")

    assert not get_user_model().objects.get(username="ivanova").is_active


def test_schedule_api_fill_list_copy_and_on_shift(admin_api) -> None:
    employee = new_employee(admin_api).json()
    template = IntervalTemplate.objects.get(name="Дневная 9–21")

    filled = admin_api.post(
        "/api/staff/intervals/fill/",
        {"users": [employee["user_id"]], "days": ["2026-11-02", "2026-11-03"], "template": str(template.pk)},
        format="json",
    )  # fmt: skip
    week = admin_api.get("/api/staff/intervals/?from=2026-11-02&to=2026-11-08").json()
    copied = admin_api.post(
        "/api/staff/intervals/copy-week/", {"from": "2026-11-02", "to": "2026-11-09"}, format="json"
    )
    clash = admin_api.post(
        "/api/staff/intervals/",
        {"user": employee["user_id"], "start": "2026-11-02T10:00:00+03:00", "end": "2026-11-02T11:00:00+03:00",
         "interval_type": str(IntervalType.objects.get(name="Приём").pk)},
        format="json",
    )  # fmt: skip

    assert filled.json()["created"] == 2
    assert [i["type_name"] for i in week] == ["Приём", "Приём"]
    assert copied.json()["created"] == 2
    assert "Пересекается" in clash.json()["non_field_errors"][0]
    assert admin_api.get("/api/staff/intervals/on-shift/").status_code == 200
    assert admin_api.get("/api/staff/intervals/").status_code == 400  # без периода
