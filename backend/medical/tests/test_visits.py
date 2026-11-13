"""Поиск по медкарте."""

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from clients import services as clients


def test_search_finds_visits_by_text_and_diagnosis(db, django_user_model) -> None:
    """Врач ищет по тексту приёма: «когда я писал про отит»."""
    from clients.models import Breed, Client, Pet
    from medical.models import Visit
    from scheduling.models import VisitPurpose

    owner = clients.save_client(Client(last_name="Петров"))
    breed = Breed.objects.first()
    pet = clients.save_pet(Pet(owner=owner, name="Рекс", species=breed.species, breed=breed))
    doctor = django_user_model.objects.create_user(username="doc", password="x")
    purpose = VisitPurpose.objects.first()
    Visit.objects.create(
        pet=pet,
        client=owner,
        doctor=doctor,
        date=timezone.now(),
        purpose=purpose,
        treatment_html="<p>Наружный отит слева, назначены капли</p>",
    )
    Visit.objects.create(
        pet=pet,
        client=owner,
        doctor=doctor,
        date=timezone.now(),
        purpose=purpose,
        treatment_html="<p>Плановая вакцинация</p>",
    )
    api = APIClient()
    api.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))

    found = api.get("/api/medical/visits/?search=отит").json()

    rows = found["results"] if isinstance(found, dict) else found
    assert len(rows) == 1 and "отит" in rows[0]["treatment_html"]
