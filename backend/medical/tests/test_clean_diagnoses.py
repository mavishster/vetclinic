"""Уборка названий диагнозов после переноса из VetManager."""

from io import StringIO

import pytest
from django.core.management import call_command

from medical.models import Diagnosis, VisitDiagnosis


@pytest.mark.django_db
def test_tags_removed_and_first_letter_capitalized() -> None:
    Diagnosis.objects.create(name="<br/>Спленит")
    Diagnosis.objects.create(name="акне")
    Diagnosis.objects.create(name="Спондилез")

    call_command("clean_diagnoses", stdout=StringIO())

    names = set(Diagnosis.objects.values_list("name", flat=True))
    assert {"Спленит", "Акне", "Спондилез"} <= names


@pytest.mark.django_db
def test_duplicates_are_merged_keeping_visits(django_user_model) -> None:
    """После уборки «<br/>Абсцесс» и «Абсцесс» — один диагноз; приёмы не теряются."""
    from django.utils import timezone

    from clients import services as clients
    from clients.models import Breed, Client, Pet
    from medical.models import Visit
    from scheduling.models import VisitPurpose

    good = Diagnosis.objects.create(name="Абсцесс")
    dirty = Diagnosis.objects.create(name="<br/>Абсцесс")
    owner = clients.save_client(Client(last_name="Петров"))
    breed = Breed.objects.first()
    pet = clients.save_pet(Pet(owner=owner, name="Рекс", species=breed.species, breed=breed))
    visit = Visit.objects.create(
        pet=pet,
        client=owner,
        date=timezone.now(),
        purpose=VisitPurpose.objects.first(),
        doctor=django_user_model.objects.create_user(username="doc", password="x"),
    )
    VisitDiagnosis.objects.create(visit=visit, diagnosis=dirty)

    call_command("clean_diagnoses", stdout=StringIO())

    assert Diagnosis.objects.filter(name__icontains="абсцесс").count() == 1
    assert VisitDiagnosis.objects.get(visit=visit).diagnosis == good


@pytest.mark.django_db
def test_dry_run_changes_nothing() -> None:
    Diagnosis.objects.create(name="<br/>Спленит")

    out = StringIO()
    call_command("clean_diagnoses", "--dry-run", stdout=out)

    assert Diagnosis.objects.filter(name="<br/>Спленит").exists()
    assert "Спленит" in out.getvalue()
