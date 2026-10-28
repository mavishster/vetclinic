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
