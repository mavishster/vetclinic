"""Фоновые задачи: то, что не должно задерживать работу (SMS, напоминания, выгрузка в облако).

    from core.tasks import run_in_background
    run_in_background("notifications.tasks.send_sms", phone, text)

- Задача ставится в очередь только после успешной фиксации транзакции:
  если операция отменилась, задача не уйдёт (PROJECT_PLAN 4.3, правило 3).
- В задаче действует тот же пользователь, что её поставил: журнал аудита
  и «кто изменил» остаются правильными.
- Функцию передавайте строкой «модуль.функция» — так задача не зависит
  от импорта модулей верхних уровней в ядре.
"""

from importlib import import_module
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django_q.tasks import async_task

from core.context import acting_user, get_current_user


def run_in_background(func_path: str, *args: Any, **kwargs: Any) -> None:
    """Поставить задачу в очередь после фиксации текущей транзакции."""
    user = get_current_user()
    user_id = str(user.pk) if user is not None else None
    transaction.on_commit(
        lambda: async_task("core.tasks.execute", func_path, user_id, args, kwargs)
    )


def execute(
    func_path: str, user_id: str | None, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> Any:
    """Выполняется в процессе worker: восстанавливает пользователя и вызывает функцию."""
    module_path, func_name = func_path.rsplit(".", 1)
    func = getattr(import_module(module_path), func_name)
    user = get_user_model().objects.filter(pk=user_id).first() if user_id else None
    with acting_user(user):
        return func(*args, **kwargs)


def ping() -> str:
    """Проверочная задача для `make ping-worker`: результат — в админке, «Фоновые задачи»."""
    return "pong"
