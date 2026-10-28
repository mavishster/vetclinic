import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from core.context import CurrentUserMiddleware, acting_user, get_current_user


def test_acting_user_is_reset_after_block() -> None:
    marker = object()

    with acting_user(marker):  # type: ignore[arg-type]
        assert get_current_user() is marker

    assert get_current_user() is None


@pytest.mark.django_db
def test_middleware_sets_user_only_during_request() -> None:
    user = get_user_model().objects.create_user(username="ivanov", password="x")
    request = RequestFactory().get("/")
    request.user = user
    seen = []

    CurrentUserMiddleware(lambda r: seen.append(get_current_user()) or None)(request)

    assert seen == [user]
    assert get_current_user() is None
