"""Фоновые задачи. В тестах Django-Q выполняет их сразу (sync=True)."""

import pytest
from django.contrib.auth import get_user_model
from django_q.models import Success

from core.context import acting_user
from core.models import Clinic
from core.tasks import run_in_background


def rename_default_clinic(name: str) -> None:
    clinic = Clinic.objects.order_by("created_at").first()
    clinic.name = name
    clinic.save()


@pytest.mark.django_db
def test_task_runs_after_commit_as_the_same_user(django_capture_on_commit_callbacks) -> None:
    user = get_user_model().objects.create_user(username="ivanov", password="x")

    with acting_user(user), django_capture_on_commit_callbacks(execute=True):
        run_in_background("core.tests.test_tasks.rename_default_clinic", "Ветклиника «Айболит»")

    clinic = Clinic.objects.order_by("created_at").first()
    assert clinic.name == "Ветклиника «Айболит»"
    assert clinic.updated_by == user


@pytest.mark.django_db
def test_task_is_not_queued_if_transaction_is_rolled_back(
    django_capture_on_commit_callbacks,
) -> None:
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        run_in_background("core.tasks.ping")
    # Транзакция не зафиксирована: колбэки не выполняются — задача не уходит.

    assert len(callbacks) == 1
    assert not Success.objects.exists()


@pytest.mark.django_db
def test_ping_task_result_is_stored(django_capture_on_commit_callbacks) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        run_in_background("core.tasks.ping")

    assert Success.objects.get().result == "pong"
