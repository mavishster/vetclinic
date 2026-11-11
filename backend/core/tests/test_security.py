"""Безопасность: блокировка подбора пароля, защита оплаты, права на всех адресах API."""

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


def login(api: APIClient, password: str, ip: str = "10.0.0.5"):
    return api.post(
        "/api/core/auth/login/",
        {"username": "doc", "password": password},
        format="json",
        REMOTE_ADDR=ip,
    )


def test_login_locks_after_many_wrong_passwords(db, settings) -> None:
    settings.LOGIN_MAX_ATTEMPTS = 3
    get_user_model().objects.create_user(username="doc", password="Right-pass-2026")
    api = APIClient()

    codes = [login(api, "wrong").status_code for _ in range(3)]
    locked = login(api, "Right-pass-2026")  # даже верный пароль — пока блокировка

    assert codes == [400, 400, 429]  # третья неверная — сразу сообщение о блокировке
    assert locked.status_code == 429 and "заблокирован до" in locked.json()["detail"]


def test_success_resets_counter(db, settings) -> None:
    settings.LOGIN_MAX_ATTEMPTS = 3
    get_user_model().objects.create_user(username="doc", password="Right-pass-2026")
    api = APIClient()

    login(api, "wrong")
    login(api, "wrong")
    assert login(api, "Right-pass-2026").status_code == 200
    login(api, "wrong")
    login(api, "wrong")
    assert login(api, "Right-pass-2026").status_code == 200  # счётчик сброшен после удачного входа


def _api_routes():
    def walk(patterns, prefix=""):
        for p in patterns:
            if isinstance(p, URLResolver):
                yield from walk(p.url_patterns, prefix + str(p.pattern))
            elif isinstance(p, URLPattern):
                yield prefix + str(p.pattern)

    for route in walk(get_resolver().url_patterns):
        if (
            route.startswith("api/")
            and "<" not in route
            and "(?P" not in route
            and "^" not in route
        ):
            yield "/" + route


# Логотип клиники открыт нарочно: он виден на экране входа, до входа в систему.
PUBLIC = {"/api/core/health/", "/api/core/auth/csrf/", "/api/core/clinic/logo/"}
FOR_EVERY_EMPLOYEE = PUBLIC | {"/api/core/me/", "/api/core/clinic/"}


def test_every_api_address_needs_login_and_rights(db) -> None:
    """Обход всех адресов API: без входа открыты только «жив ли сервер» и CSRF,
    сотруднику без прав — только его профиль и реквизиты клиники."""
    user = get_user_model().objects.create_user(username="nobody", password="x")
    employee = APIClient()
    employee.force_authenticate(user)
    anonymous = APIClient()
    routes = [r for r in _api_routes() if not r.rstrip("/").endswith(("/api/core", "/api/clients"))]

    open_anon = {r for r in routes if anonymous.get(r).status_code < 400}
    open_employee = {r for r in routes if employee.get(r).status_code < 400}

    assert open_anon <= PUBLIC
    roots = {
        r for r in open_employee if r.count("/") == 3
    }  # корневые списки разделов API — без данных
    assert open_employee - roots <= FOR_EVERY_EMPLOYEE
