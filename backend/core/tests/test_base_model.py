"""Правила базовой модели (ADR-002, ADR-003). Проверяются на модели Clinic."""

import uuid

import pytest
from django.contrib.auth import get_user_model

from core.context import acting_user
from core.models import Clinic

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="ivanov", password="x")


@pytest.mark.django_db
def test_new_record_gets_uuid_node_and_first_version(settings) -> None:
    settings.NODE_ID = "K7"

    clinic = Clinic.objects.create(name="Филиал")

    assert isinstance(clinic.id, uuid.UUID)
    assert clinic.node_id == "K7"
    assert clinic.version == 1


@pytest.mark.django_db
def test_version_grows_on_every_save() -> None:
    clinic = Clinic.objects.create(name="Филиал")

    clinic.name = "Филиал на Ленина"
    clinic.save()
    clinic.save(update_fields=["name"])

    clinic.refresh_from_db()
    assert clinic.version == 3


def test_author_and_editor_are_filled_from_acting_user(user) -> None:
    editor = User.objects.create_user(username="petrov", password="x")

    with acting_user(user):
        clinic = Clinic.objects.create(name="Филиал")
    with acting_user(editor):
        clinic.save()

    clinic.refresh_from_db()
    assert clinic.created_by == user
    assert clinic.updated_by == editor


@pytest.mark.django_db
def test_delete_is_soft_and_restore_brings_record_back() -> None:
    clinic = Clinic.objects.create(name="Филиал")

    clinic.delete()

    assert not Clinic.objects.filter(pk=clinic.pk).exists()
    assert Clinic.all_objects.get(pk=clinic.pk).is_deleted

    clinic.restore()

    assert Clinic.objects.filter(pk=clinic.pk).exists()


@pytest.mark.django_db
def test_bulk_delete_is_soft_and_bumps_version() -> None:
    clinic = Clinic.objects.create(name="Филиал")

    Clinic.objects.filter(pk=clinic.pk).delete()

    stored = Clinic.all_objects.get(pk=clinic.pk)
    assert stored.is_deleted
    assert stored.version == 2
