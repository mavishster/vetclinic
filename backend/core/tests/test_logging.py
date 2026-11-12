"""Ошибки сервера должны попадать в журнал: иначе поломка на сервере выглядит как «500»
без объяснения, и причину не найти."""

import logging

import pytest
from django.urls import path
from rest_framework.test import APIClient


def boom(request):  # pragma: no cover — вызывается через тестовые адреса
    raise RuntimeError("тестовая поломка")


urlpatterns = [path("boom/", boom)]


@pytest.mark.django_db
def test_server_error_is_logged(settings, caplog) -> None:
    settings.ROOT_URLCONF = __name__
    settings.DEBUG = False
    settings.ALLOWED_HOSTS = ["testserver"]
    api = APIClient(raise_request_exception=False)

    with caplog.at_level(logging.ERROR, logger="django.request"):
        response = api.get("/boom/")

    assert response.status_code == 500
    assert any(
        "тестовая поломка" in record.getMessage() or record.exc_info for record in caplog.records
    )


def test_logging_is_configured(settings) -> None:
    """Ошибки идут в вывод контейнера, а не в никуда."""
    assert settings.LOGGING["loggers"]["django.request"]["handlers"] == ["console"]
    assert settings.LOGGING["handlers"]["console"]["class"] == "logging.StreamHandler"
