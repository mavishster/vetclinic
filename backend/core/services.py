"""Ядро: публичный вход модуля.

Отвечает за: базовые модели, документы, журнал движений, справочники, права,
аудит, нумерацию, печать.

Другие модули обращаются к модулю только через функции этого файла.
Бизнес-правила живут здесь, а не в моделях и не в API (ENGINEERING.md).
"""

import itertools
from datetime import timedelta
from typing import TypedDict

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import Group, Permission
from django.db import DatabaseError, connection
from django.utils import timezone

from core.models import Clinic, User


class HealthStatus(TypedDict):
    status: str
    database: bool


def health() -> HealthStatus:
    """Проверка работоспособности: отвечает ли приложение и доступна ли база."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        database_ok = True
    except DatabaseError:
        database_ok = False
    return {"status": "ok" if database_ok else "degraded", "database": database_ok}


def current_clinic() -> Clinic:
    """Клиника, в которой работает система.

    В первой версии клиника одна (создаётся миграцией). Когда появится второй
    филиал, здесь будет выбор по пользователю или узлу — вызывающий код не изменится.
    """
    clinic = Clinic.objects.order_by("created_at").first()
    if clinic is None:
        raise Clinic.DoesNotExist("Клиника не создана: примените миграции ядра.")
    return clinic


# --- ПИН-код для подтверждения операций (ADR-014) ---------------------------------


class PinError(Exception):
    """Подтверждение ПИН-кодом не прошло. Текст — для пользователя."""


def _is_trivial_pin(pin: str) -> bool:
    """0000, 1111, 1234, 4321 и подобные угадываются первыми."""
    digits = [int(d) for d in pin]
    steps = {b - a for a, b in itertools.pairwise(digits)}
    return steps in ({0}, {1}, {-1})


def set_pin(user: User, pin: str) -> None:
    """Задать или сменить ПИН: 4–6 цифр, не слишком простой."""
    if not (pin.isdigit() and 4 <= len(pin) <= 6):
        raise PinError("ПИН должен состоять из 4–6 цифр.")
    if _is_trivial_pin(pin):
        raise PinError("ПИН слишком простой: не используйте одинаковые цифры или 1234.")
    user.pin_hash = make_password(pin)
    user.pin_failed_attempts = 0
    user.pin_locked_until = None
    user.save(update_fields=["pin_hash", "pin_failed_attempts", "pin_locked_until"])


def reset_pin(user: User) -> None:
    """Сбросить ПИН (например, сотрудник его забыл). Задать новый сможет сам сотрудник."""
    user.pin_hash = ""
    user.pin_failed_attempts = 0
    user.pin_locked_until = None
    user.save(update_fields=["pin_hash", "pin_failed_attempts", "pin_locked_until"])


def confirm_action(user: User, pin: str) -> None:
    """Проверить ПИН перед важной операцией. При ошибке — PinError с понятным текстом.

    После settings.PIN_MAX_ATTEMPTS неверных попыток ПИН блокируется
    на settings.PIN_LOCK_MINUTES минут.
    """
    if not user.has_pin:
        raise PinError("ПИН не задан. Задайте его в своём профиле.")
    now = timezone.now()
    if user.pin_locked_until and user.pin_locked_until > now:
        until = timezone.localtime(user.pin_locked_until).strftime("%H:%M")
        raise PinError(f"ПИН заблокирован из-за неверных попыток до {until}.")
    if check_password(pin, user.pin_hash):
        if user.pin_failed_attempts:
            user.pin_failed_attempts = 0
            user.save(update_fields=["pin_failed_attempts"])
        return
    user.pin_failed_attempts += 1
    left = settings.PIN_MAX_ATTEMPTS - user.pin_failed_attempts
    if left <= 0:
        user.pin_failed_attempts = 0
        user.pin_locked_until = now + timedelta(minutes=settings.PIN_LOCK_MINUTES)
        user.save(update_fields=["pin_failed_attempts", "pin_locked_until"])
        raise PinError(f"Неверный ПИН. ПИН заблокирован на {settings.PIN_LOCK_MINUTES} минут.")
    user.save(update_fields=["pin_failed_attempts"])
    raise PinError(f"Неверный ПИН. Осталось попыток: {left}.")


# --- Роли и права по модулям (ADR-013) ---------------------------------------------

# Действие в матрице «роль × модуль × действие» → стандартные права Django.
MODULE_ACTIONS: dict[str, tuple[str, ...]] = {
    "view": ("view",),
    "edit": ("add", "change"),
    "delete": ("delete",),
}


def _module_permissions(app_label: str, action: str) -> list[Permission]:
    prefixes = MODULE_ACTIONS[action]
    return [
        perm
        for perm in Permission.objects.filter(content_type__app_label=app_label)
        if perm.codename.split("_", 1)[0] in prefixes
        # История изменений — служебные модели, права на них отдельно не раздаём.
        and not perm.content_type.model.startswith("historical")
    ]


def set_module_permissions(role: Group, app_label: str, actions: set[str]) -> None:
    """Назначить роли действия в модуле целиком: {"view", "edit", "delete"}.

    Права модуля, не попавшие в actions, у роли снимаются.
    """
    unknown = actions - MODULE_ACTIONS.keys()
    if unknown:
        raise ValueError(f"Неизвестные действия: {', '.join(sorted(unknown))}")
    for action in MODULE_ACTIONS:
        perms = _module_permissions(app_label, action)
        if action in actions:
            role.permissions.add(*perms)
        else:
            role.permissions.remove(*perms)


def module_actions(role: Group, app_label: str) -> set[str]:
    """Какие действия модуля есть у роли (действие есть, если есть все его права)."""
    granted = set(role.permissions.values_list("pk", flat=True))
    result = set()
    for action in MODULE_ACTIONS:
        perms = _module_permissions(app_label, action)
        if perms and all(perm.pk in granted for perm in perms):
            result.add(action)
    return result
