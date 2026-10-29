import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from clients import services
from clients.models import Breed, Client, Pet, Species

URL = "/api/clients/pets/"


@pytest.fixture
def api(db):
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    return client


@pytest.fixture
def owner(db):
    return services.save_client(Client(last_name="Иванова"))


@pytest.fixture
def cat_data(db):
    cats = Species.objects.get(name="Кошки")
    return {
        "name": "Барсик",
        "species": str(cats.pk),
        "breed": str(Breed.objects.get(name="Метис", species=cats).pk),
    }


def test_create_pet_and_list_by_owner(api, owner, cat_data) -> None:
    created = api.post(URL, {**cat_data, "owner": str(owner.pk), "sex": "male"}, format="json")

    assert created.status_code == 201
    assert created.json()["owner_name"] == "Иванова"
    assert created.json()["breed_name"] == "Метис"
    pets = api.get(f"{URL}?owner={owner.pk}").json()["results"]
    assert [p["name"] for p in pets] == ["Барсик"]
    client = api.get(f"/api/clients/clients/{owner.pk}/").json()
    assert client["pet_names"] == ["Барсик"]


def test_wrong_breed_is_readable_error(api, owner, cat_data) -> None:
    dog_breed = Breed.objects.get(name="Метис", species__name="Собаки")

    response = api.post(
        URL, {**cat_data, "owner": str(owner.pk), "breed": str(dog_breed.pk)}, format="json"
    )

    assert response.status_code == 400
    assert "Порода" in response.json()["non_field_errors"][0]


def test_owner_cannot_be_changed_by_edit(api, owner, cat_data) -> None:
    pet_id = api.post(URL, {**cat_data, "owner": str(owner.pk)}, format="json").json()["id"]
    other = services.save_client(Client(last_name="Петров"))

    api.patch(f"{URL}{pet_id}/", {"owner": str(other.pk), "name": "Барс"}, format="json")

    pet = Pet.objects.get(pk=pet_id)
    assert pet.owner == owner
    assert pet.name == "Барс"


def test_transfer_and_former_pets(api, owner, cat_data) -> None:
    pet_id = api.post(URL, {**cat_data, "owner": str(owner.pk)}, format="json").json()["id"]
    other = services.save_client(Client(last_name="Петров"))

    response = api.post(f"{URL}{pet_id}/transfer/", {"owner": str(other.pk)}, format="json")
    again = api.post(f"{URL}{pet_id}/transfer/", {"owner": str(other.pk)}, format="json")
    former = api.get(f"{URL}?former_of={owner.pk}").json()["results"]

    assert response.json()["owner_name"] == "Петров"
    assert again.status_code == 400
    assert [p["id"] for p in former] == [pet_id]


def test_death_and_weights(api, owner, cat_data) -> None:
    pet_id = api.post(URL, {**cat_data, "owner": str(owner.pk)}, format="json").json()["id"]

    added = api.post(f"{URL}{pet_id}/weights/", {"weight": "4.25"}, format="json")
    bad = api.post(f"{URL}{pet_id}/weights/", {"weight": "-1"}, format="json")
    history = api.get(f"{URL}{pet_id}/weights/").json()
    dead = api.post(f"{URL}{pet_id}/death/", {}, format="json")

    assert added.status_code == 201
    assert bad.status_code == 400
    assert history[0]["weight"] == "4.250"
    assert dead.json()["status"] == "dead"
    assert api.get(f"{URL}{pet_id}/").json()["weight"]["weight"] == "4.250"


def test_view_only_role_cannot_transfer(db, owner, cat_data) -> None:
    from django.contrib.auth.models import Group

    from core import services as core

    role = Group.objects.create(name="Только просмотр")
    core.set_entity_permissions(role, "clients.pet", {"view"})
    user = get_user_model().objects.create_user(username="v", password="x")
    user.groups.add(role)
    client = APIClient()
    client.force_authenticate(user)
    cats = Species.objects.get(name="Кошки")
    pet = services.save_pet(
        Pet(
            owner=owner,
            name="Барсик",
            species=cats,
            breed=Breed.objects.get(name="Метис", species=cats),
        )
    )

    assert client.get(f"{URL}{pet.pk}/").status_code == 200
    assert client.post(f"{URL}{pet.pk}/death/", {}, format="json").status_code == 403
