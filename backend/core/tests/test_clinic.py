import pytest

from core import services
from core.models import Clinic


@pytest.mark.django_db
def test_default_clinic_exists_after_migrations() -> None:
    assert services.current_clinic().name == "Клиника"


@pytest.mark.django_db
def test_current_clinic_is_the_first_created() -> None:
    first = services.current_clinic()
    Clinic.objects.create(name="Второй филиал")

    assert services.current_clinic() == first
