import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


def test_full_and_short_name() -> None:
    user = User(username="u", last_name="Иванова", first_name="Анна", middle_name="Петровна")

    assert user.full_name == "Иванова Анна Петровна"
    assert user.short_name == "Иванова А. П."
    assert str(user) == "Иванова А. П."


def test_name_without_middle_name_and_fallback_to_login() -> None:
    assert User(username="u", last_name="Смит", first_name="Джон").short_name == "Смит Д."
    assert str(User(username="reception")) == "reception"


@pytest.mark.django_db
def test_user_id_is_uuid_and_version_grows() -> None:
    user = User.objects.create_user(username="ivanov", password="x")

    user.first_name = "Иван"
    user.save()

    assert len(str(user.pk)) == 36
    assert user.version == 2
