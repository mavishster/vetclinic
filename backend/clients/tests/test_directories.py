"""Справочники видов и пород — и через них общий механизм справочников ядра."""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from rest_framework.test import APIClient

from clients.models import Breed, Species


@pytest.fixture
def api(db):
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_user(username="u", password="x"))
    return client


@pytest.fixture
def cats(db):
    return Species.objects.get(name="Кошки")


@pytest.mark.django_db
def test_initial_species_are_created_by_migration() -> None:
    assert {"Кошки", "Собаки", "Грызуны"} <= set(Species.objects.values_list("name", flat=True))


@pytest.mark.django_db
def test_name_is_unique_case_insensitive_at_database_level() -> None:
    with pytest.raises(IntegrityError):
        Species.objects.create(name="кошки")


@pytest.mark.django_db
def test_name_can_be_reused_after_soft_delete(cats) -> None:
    cats.delete()

    assert Species.objects.create(name="Кошки").pk != cats.pk


@pytest.mark.django_db
def test_same_breed_name_allowed_in_different_species(cats) -> None:
    dogs = Species.objects.get(name="Собаки")
    Breed.objects.create(name="Метис", species=cats)

    Breed.objects.create(name="Метис", species=dogs)

    with pytest.raises(IntegrityError):
        Breed.objects.create(name="метис", species=cats)


def test_api_requires_login(db) -> None:
    assert APIClient().get("/api/clients/species/").status_code == 403


def test_api_list_is_sorted_and_filters_by_activity_and_search(api, cats) -> None:
    cats.is_active = False
    cats.save()

    names = [row["name"] for row in api.get("/api/clients/species/").json()]
    active = [row["name"] for row in api.get("/api/clients/species/?active=true").json()]
    found = [row["name"] for row in api.get("/api/clients/species/?search=соб").json()]

    assert names == sorted(names)
    assert "Кошки" in names and "Кошки" not in active
    assert found == ["Собаки"]


def test_api_create_trims_name_and_rejects_duplicates(api) -> None:
    created = api.post("/api/clients/species/", {"name": "  Ежи  "}, format="json")
    duplicate = api.post("/api/clients/species/", {"name": "ежи"}, format="json")
    empty = api.post("/api/clients/species/", {"name": "   "}, format="json")

    assert created.status_code == 201
    assert created.json()["name"] == "Ежи"
    assert duplicate.status_code == 400
    assert duplicate.json()["name"] == ["Такая запись уже есть в справочнике."]
    assert empty.status_code == 400


def test_api_rename_to_own_name_is_allowed(api, cats) -> None:
    response = api.patch(f"/api/clients/species/{cats.pk}/", {"name": "Кошки"}, format="json")

    assert response.status_code == 200


def test_api_deactivate_and_soft_delete(api) -> None:
    hedgehogs = Species.objects.create(name="Ежи")

    api.patch(f"/api/clients/species/{hedgehogs.pk}/", {"is_active": False}, format="json")
    hedgehogs.refresh_from_db()
    assert not hedgehogs.is_active

    assert api.delete(f"/api/clients/species/{hedgehogs.pk}/").status_code == 204
    assert Species.all_objects.get(pk=hedgehogs.pk).is_deleted


def test_api_breeds_filter_by_species_and_unique_within_species(api, cats) -> None:
    dogs = Species.objects.get(name="Собаки")
    Breed.objects.create(name="Мейн-кун", species=cats)
    Breed.objects.create(name="Метис", species=dogs)

    cat_breeds = api.get(f"/api/clients/breeds/?species={cats.pk}").json()
    same_in_dogs = api.post(
        "/api/clients/breeds/", {"name": "Метис", "species": str(cats.pk)}, format="json"
    )
    duplicate = api.post(
        "/api/clients/breeds/", {"name": "мейн-кун", "species": str(cats.pk)}, format="json"
    )

    assert [b["name"] for b in cat_breeds] == ["Мейн-кун"]
    assert same_in_dogs.status_code == 201
    assert duplicate.status_code == 400
