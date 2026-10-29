"""Роли и права: таблица «модуль × действие» и состав роли (ADR-013)."""

from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from core import services
from core.models import User

ACTIONS = list(services.MODULE_ACTIONS)


class RoleSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    users = serializers.PrimaryKeyRelatedField(
        source="user_set", many=True, queryset=get_user_model().objects.all(), required=False
    )
    modules = serializers.DictField(
        child=serializers.ListField(child=serializers.ChoiceField(choices=ACTIONS)),
        required=False,
        help_text='{"clients": ["view", "edit"], ...}',
    )

    class Meta:
        model = Group
        fields = ["id", "name", "users", "modules"]

    def to_representation(self, role: Group) -> dict[str, Any]:
        data = super().to_representation(role)
        data["modules"] = {
            code: sorted(services.module_actions(role, code))
            for code, _ in services.permission_modules()
        }
        return data

    def validate_modules(self, value: dict[str, list[str]]) -> dict[str, list[str]]:
        known = {code for code, _ in services.permission_modules()}
        unknown = set(value) - known
        if unknown:
            raise serializers.ValidationError(f"Неизвестные модули: {', '.join(sorted(unknown))}")
        return value

    @transaction.atomic
    def save(self, **kwargs: Any) -> Group:
        modules = self.validated_data.pop("modules", None)
        role: Group = super().save(**kwargs)
        for code, actions in (modules or {}).items():
            services.set_module_permissions(role, code, set(actions))
        return role


class RoleViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]
    queryset = Group.objects.order_by("name")
    serializer_class = RoleSerializer

    @action(detail=False, methods=["get"])
    def matrix(self, request: Request) -> Response:
        """Строки и столбцы таблицы прав: модули и действия."""
        return Response(
            {
                "modules": [{"code": c, "title": t} for c, t in services.permission_modules()],
                "actions": [
                    {"code": "view", "title": "Просмотр"},
                    {"code": "edit", "title": "Редактирование"},
                    {"code": "delete", "title": "Удаление"},
                ],
            }
        )


class UserListSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    class Meta:
        model = User
        fields = ["id", "username", "full_name", "short_name", "is_active"]


class UserViewSet(viewsets.ReadOnlyModelViewSet):  # type: ignore[type-arg]
    """Список сотрудников — для выбора состава роли."""

    queryset = User.objects.filter(is_active=True).order_by("last_name", "first_name")
    serializer_class = UserListSerializer
