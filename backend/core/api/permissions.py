"""Права доступа к API по ролям (ADR-013).

Роль — это группа Django. Права — стандартные права моделей Django:
просмотр (view), добавление (add), изменение (change), удаление (delete).
Права по модулю целиком назначаются функцией core.services.set_module_permissions().
"""

from rest_framework.permissions import DjangoModelPermissions


class ModelPermissions(DjangoModelPermissions):
    """Как DjangoModelPermissions, но для чтения тоже нужно право просмотра."""

    perms_map = {
        **DjangoModelPermissions.perms_map,
        "GET": ["%(app_label)s.view_%(model_name)s"],
        "HEAD": ["%(app_label)s.view_%(model_name)s"],
        "OPTIONS": ["%(app_label)s.view_%(model_name)s"],
    }
