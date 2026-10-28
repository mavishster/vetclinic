from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from core import services
from core.services import PinError


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="cashier", password="x")


@pytest.mark.parametrize("pin", ["123", "1234567", "12a4", ""])
def test_pin_must_be_4_to_6_digits(user, pin) -> None:
    with pytest.raises(PinError, match="4–6 цифр"):
        services.set_pin(user, pin)


@pytest.mark.parametrize("pin", ["0000", "1111", "1234", "4321", "345678"])
def test_trivial_pins_are_rejected(user, pin) -> None:
    with pytest.raises(PinError, match="слишком простой"):
        services.set_pin(user, pin)


def test_pin_is_stored_as_hash_and_confirms(user) -> None:
    services.set_pin(user, "2580")

    assert "2580" not in user.pin_hash
    services.confirm_action(user, "2580")


def test_confirm_without_pin_asks_to_set_it(user) -> None:
    with pytest.raises(PinError, match="не задан"):
        services.confirm_action(user, "2580")


def test_wrong_pin_reports_attempts_left_and_locks(user, settings) -> None:
    settings.PIN_MAX_ATTEMPTS = 3
    services.set_pin(user, "2580")

    with pytest.raises(PinError, match="Осталось попыток: 2"):
        services.confirm_action(user, "0001")
    with pytest.raises(PinError, match="Осталось попыток: 1"):
        services.confirm_action(user, "0001")
    with pytest.raises(PinError, match="заблокирован на"):
        services.confirm_action(user, "0001")
    with pytest.raises(PinError, match="заблокирован .* до"):
        services.confirm_action(user, "2580")


def test_lock_expires(user) -> None:
    services.set_pin(user, "2580")
    user.pin_locked_until = timezone.now() - timedelta(minutes=1)
    user.save()

    services.confirm_action(user, "2580")


def test_correct_pin_resets_failed_attempts(user) -> None:
    services.set_pin(user, "2580")
    with pytest.raises(PinError):
        services.confirm_action(user, "0001")

    services.confirm_action(user, "2580")

    user.refresh_from_db()
    assert user.pin_failed_attempts == 0


def test_reset_pin(user) -> None:
    services.set_pin(user, "2580")

    services.reset_pin(user)

    assert not user.has_pin
