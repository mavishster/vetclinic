"""Права доступа к API по ролям (ADR-013).

Роль — это группа Django. Права — стандартные права моделей Django:
просмотр (view), добавление (add), изменение (change), удаление (delete).
Права по модулю целиком назначаются функцией core.services.set_module_permissions().
"""

from typing import Any

from rest_framework.permissions import DjangoModelPermissions


class ModelPermissions(DjangoModelPermissions):
    """Как DjangoModelPermissions, но для чтения тоже нужно право просмотра."""

    perms_map = {
        **DjangoModelPermissions.perms_map,
        "GET": ["%(app_label)s.view_%(model_name)s"],
        "HEAD": ["%(app_label)s.view_%(model_name)s"],
        "OPTIONS": ["%(app_label)s.view_%(model_name)s"],
    }


SPECIAL_DENIED = "Нет особого права «{title}». Его выдаёт тот, кто настраивает роли."


def require_special(request: Any, code: str) -> None:
    """Особое право (откат, возврат, закрытие кассы…) — иначе понятный отказ 403."""
    from rest_framework.exceptions import PermissionDenied

    from core import services

    if request.user.has_perm(code):
        return
    title = next(
        (
            sp["title"]
            for m in services.permission_modules()
            for sp in m["special"]
            if sp["code"] == code
        ),
        code,
    )
    raise PermissionDenied(SPECIAL_DENIED.format(title=title))


def can_view_cost(request: Any) -> bool:
    """Себестоимость, закупочные цены и прибыль видны только с особым правом."""
    return bool(request and request.user.has_perm("catalog.view_cost"))
