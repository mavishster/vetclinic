"""Вход с защитой от подбора пароля.

После LOGIN_MAX_ATTEMPTS неверных попыток подряд вход под этим логином блокируется на
LOGIN_LOCK_MINUTES минут; с одного адреса — после LOGIN_MAX_ATTEMPTS_PER_IP попыток
(перебор разных логинов). Действует и для входа в систему, и для /admin.
Счётчики — в общем кэше (файлы), чтобы их видели все процессы сервера.
"""

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.core.cache import cache
from django.utils import timezone


def _client_ip(request: Any) -> str:
    if request is None:
        return ""
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR", "")


def _keys(request: Any, username: str) -> tuple[str, str]:
    return f"login-fail:user:{(username or '').lower()}", f"login-fail:ip:{_client_ip(request)}"


def locked_until(request: Any, username: str) -> Any:
    """До какого времени вход заблокирован (или None)."""
    user_key, ip_key = _keys(request, username)
    return cache.get(f"{user_key}:lock") or cache.get(f"{ip_key}:lock")


class ThrottledModelBackend(ModelBackend):
    """Обычная проверка логина и пароля + блокировка после серии неверных попыток."""

    def authenticate(
        self, request: Any, username: str | None = None, password: str | None = None, **kwargs: Any
    ) -> Any:
        if locked_until(request, username or ""):
            return None
        user = super().authenticate(request, username=username, password=password, **kwargs)
        user_key, ip_key = _keys(request, username or "")
        if user is not None:
            cache.delete_many([user_key, f"{user_key}:lock"])
            return user
        lock = timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
        for key, limit in (
            (user_key, settings.LOGIN_MAX_ATTEMPTS),
            (ip_key, settings.LOGIN_MAX_ATTEMPTS_PER_IP),
        ):
            failures = (cache.get(key) or 0) + 1
            cache.set(key, failures, lock.total_seconds())
            if failures >= limit:
                cache.set(f"{key}:lock", timezone.now() + lock, lock.total_seconds())
                cache.delete(key)
        return None
