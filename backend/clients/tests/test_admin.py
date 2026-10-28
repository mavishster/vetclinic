import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from clients.models import Species


@pytest.fixture
def admin_client(client, db):
    client.force_login(get_user_model().objects.create_superuser(username="admin", password="x"))
    return client


@pytest.mark.parametrize("model", ["species", "breed"])
def test_directory_admin_pages_open(admin_client, model) -> None:
    assert admin_client.get(reverse(f"admin:clients_{model}_changelist")).status_code == 200
    assert admin_client.get(reverse(f"admin:clients_{model}_add")).status_code == 200


def test_deactivate_action_bumps_version(admin_client) -> None:
    cats = Species.objects.get(name="Кошки")

    admin_client.post(
        reverse("admin:clients_species_changelist"),
        {"action": "deactivate", "_selected_action": [str(cats.pk)]},
    )

    cats.refresh_from_db()
    assert not cats.is_active
    assert cats.version == 2
