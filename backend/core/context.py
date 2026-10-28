"""Кто сейчас действует в системе.

Нужен базовой модели, чтобы заполнять «кто создал» и «кто изменил» без передачи
пользователя в каждый save(). В веб-запросах значение ставит middleware,
в фоновых задачах и тестах — контекстный менеджер acting_user().
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from django.http import HttpRequest, HttpResponse

if TYPE_CHECKING:
    from core.models import User

_current_user: ContextVar["User | None"] = ContextVar("current_user", default=None)


def get_current_user() -> "User | None":
    return _current_user.get()


@contextmanager
def acting_user(user: "User | None") -> Iterator[None]:
    """Выполнить блок кода от имени пользователя."""
    token = _current_user.set(user)
    try:
        yield
    finally:
        _current_user.reset(token)


class CurrentUserMiddleware:
    """Запоминает вошедшего пользователя на время обработки запроса."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = request.user if request.user.is_authenticated else None
        with acting_user(user):
            return self.get_response(request)
