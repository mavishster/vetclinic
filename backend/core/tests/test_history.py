"""Журнал аудита: кто, что и когда изменил."""

import pytest
from django.contrib.auth import get_user_model

from core.context import acting_user
from core.models import Clinic


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="ivanov", password="x")


def test_changes_are_recorded_with_author(user) -> None:
    with acting_user(user):
        clinic = Clinic.objects.create(name="Филиал")
        clinic.name = "Филиал на Ленина"
        clinic.save()

    records = list(clinic.history.order_by("history_date"))
    assert [r.name for r in records] == ["Филиал", "Филиал на Ленина"]
    assert [r.history_type for r in records] == ["+", "~"]
    assert all(r.history_user == user for r in records)


def test_soft_delete_including_bulk_is_recorded(user) -> None:
    clinic = Clinic.objects.create(name="Филиал")

    with acting_user(user):
        Clinic.objects.filter(pk=clinic.pk).delete()

    last = clinic.history.latest("history_date")
    assert last.is_deleted
    assert last.history_user == user


def test_user_history_does_not_store_secrets(db) -> None:
    user = get_user_model().objects.create_user(username="ivanov", password="secret-pass")

    fields = {f.name for f in user.history.model._meta.get_fields()}

    assert "password" not in fields
    assert "pin_hash" not in fields
