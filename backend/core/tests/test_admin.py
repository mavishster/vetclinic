import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from core import services


@pytest.fixture
def admin_client(client, db):
    admin = get_user_model().objects.create_superuser(username="admin", password="x")
    client.force_login(admin)
    client.admin_user = admin
    return client


@pytest.mark.parametrize("url_name", ["admin:core_user_changelist", "admin:core_user_add"])
def test_user_admin_pages_open(admin_client, url_name) -> None:
    assert admin_client.get(reverse(url_name)).status_code == 200


def test_user_change_page_opens(admin_client) -> None:
    url = reverse("admin:core_user_change", args=[admin_client.admin_user.pk])

    assert admin_client.get(url).status_code == 200


def test_clinic_admin_pages_open(admin_client) -> None:
    clinic = services.current_clinic()

    assert admin_client.get(reverse("admin:core_clinic_changelist")).status_code == 200
    url = reverse("admin:core_clinic_change", args=[clinic.pk])
    assert admin_client.get(url).status_code == 200


def test_user_can_be_created_with_full_name(admin_client) -> None:
    response = admin_client.post(
        reverse("admin:core_user_add"),
        {
            "username": "petrova",
            "last_name": "Петрова",
            "first_name": "Мария",
            "middle_name": "Сергеевна",
            "usable_password": "true",
            "password1": "Vet-clinic-2026",
            "password2": "Vet-clinic-2026",
        },
    )

    assert response.status_code == 302
    created = get_user_model().objects.get(username="petrova")
    assert created.full_name == "Петрова Мария Сергеевна"


def test_history_page_opens(admin_client) -> None:
    url = reverse("admin:core_clinic_history", args=[services.current_clinic().pk])

    assert admin_client.get(url).status_code == 200


def test_reset_pin_action(admin_client) -> None:
    services.set_pin(admin_client.admin_user, "2580")

    admin_client.post(
        reverse("admin:core_user_changelist"),
        {"action": "reset_pin", "_selected_action": [str(admin_client.admin_user.pk)]},
    )

    admin_client.admin_user.refresh_from_db()
    assert not admin_client.admin_user.has_pin
