import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core import services


@pytest.mark.django_db
def test_health_service_reports_database_available() -> None:
    assert services.health() == {"status": "ok", "database": True}


@pytest.mark.django_db
def test_health_endpoint_is_public_and_ok() -> None:
    response = APIClient().get(reverse("core-health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": True}
