"""Питомцы: правила карточки, смена владельца, смерть, вес, поиск."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from clients import services
from clients.models import Breed, Client, Pet, Species
from clients.services import ClientError


@pytest.fixture
def owner(db):
    return services.save_client(Client(last_name="Иванова", first_name="Анна"))


@pytest.fixture
def cats(db):
    return Species.objects.get(name="Кошки")


def make_pet(owner, cats, name="Барсик", **fields):
    breed = Breed.objects.get(name="Метис", species=cats)
    return services.save_pet(Pet(owner=owner, name=name, species=cats, breed=breed, **fields))


def test_new_pet_opens_ownership(owner, cats) -> None:
    pet = make_pet(owner, cats)

    ownership = pet.ownerships.get()
    assert ownership.client == owner
    assert ownership.date_to is None


def test_breed_must_match_species(owner, cats) -> None:
    dog_breed = Breed.objects.get(name="Метис", species__name="Собаки")

    with pytest.raises(ClientError, match="Порода не относится"):
        services.save_pet(Pet(owner=owner, name="Шарик", species=cats, breed=dog_breed))


def test_name_required_and_birth_date_not_in_future(owner, cats) -> None:
    with pytest.raises(ClientError, match="кличку"):
        make_pet(owner, cats, name="  ")
    with pytest.raises(ClientError, match="будущем"):
        make_pet(owner, cats, birth_date=timezone.localdate() + timedelta(days=1))


def test_transfer_keeps_history_and_shows_pet_as_former(owner, cats) -> None:
    pet = make_pet(owner, cats)
    new_owner = services.save_client(Client(last_name="Петров"))

    services.transfer_pet(pet, new_owner)

    pet.refresh_from_db()
    assert pet.owner == new_owner
    assert [o.client.last_name for o in pet.ownerships.all()] == ["Петров", "Иванова"]
    assert list(services.former_pets(owner)) == [pet]
    assert list(services.former_pets(new_owner)) == []


def test_transfer_to_same_owner_is_rejected(owner, cats) -> None:
    pet = make_pet(owner, cats)

    with pytest.raises(ClientError, match="уже принадлежит"):
        services.transfer_pet(pet, owner)


def test_pet_returned_to_previous_owner_is_not_former(owner, cats) -> None:
    pet = make_pet(owner, cats)
    other = services.save_client(Client(last_name="Петров"))
    services.transfer_pet(pet, other)

    services.transfer_pet(pet, owner)

    assert list(services.former_pets(owner)) == []
    assert list(services.former_pets(other)) == [pet]


def test_mark_dead_defaults_to_today_and_validates_dates(owner, cats) -> None:
    pet = make_pet(owner, cats, birth_date=date(2020, 5, 1))

    services.mark_dead(pet)
    assert pet.status == Pet.Status.DEAD
    assert pet.death_date == timezone.localdate()

    with pytest.raises(ClientError, match="раньше даты рождения"):
        services.mark_dead(pet, date(2019, 1, 1))


def test_reviving_clears_death_date(owner, cats) -> None:
    pet = make_pet(owner, cats)
    services.mark_dead(pet)

    pet.status = Pet.Status.ACTIVE
    services.save_pet(pet)

    assert pet.death_date is None


def test_weight_history_and_validation(owner, cats) -> None:
    pet = make_pet(owner, cats)

    services.add_weight(pet, Decimal("4.2"), date(2026, 1, 10))
    services.add_weight(pet, Decimal("4.5"))

    assert services.current_weight(pet).weight == Decimal("4.5")
    with pytest.raises(ClientError, match="вес"):
        services.add_weight(pet, Decimal("0"))


def test_pet_search_by_name_chip_and_owner(owner, cats) -> None:
    pet = make_pet(owner, cats, chip_number="643094100123456")
    make_pet(services.save_client(Client(last_name="Петров")), cats, name="Мурка")

    def found(text):
        return list(services.search_pets(Pet.objects.all(), text))

    assert found("барс") == [pet]
    assert found("123456") == [pet]
    assert found("иванова") == [pet]


def test_client_search_finds_by_pet_name(owner, cats) -> None:
    make_pet(owner, cats, name="Пушок")

    assert list(services.search_clients(Client.objects.all(), "пушок")) == [owner]
