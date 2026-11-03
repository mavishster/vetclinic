from django.conf import settings
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from core import services
from core.models import User


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request: Request) -> Response:
    """Состояние системы. Открыт без входа — нужен для мониторинга."""
    result = services.health()
    return Response(result, status=200 if result["database"] else 503)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request: Request) -> Response:
    """Текущий пользователь и его права — интерфейс по ним решает, что показывать."""
    user: User = request.user  # type: ignore[assignment]
    return Response(
        {
            "id": str(user.pk),
            "username": user.username,
            "full_name": user.full_name,
            "short_name": user.short_name,
            "is_superuser": user.is_superuser,
            "has_pin": user.has_pin,
            "clinic": services.current_clinic().name,
            "permissions": sorted(user.get_all_permissions()),
            "ui_settings": user.ui_settings or {},
            "currency": settings.CURRENCY,
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def backup_status(request: Request) -> Response:
    """Резервные копии: показываются тем, кто настраивает систему (право на роли)."""
    if not request.user.has_perm("auth.change_group"):
        return Response({"detail": "Недостаточно прав."}, status=403)
    return Response(services.backup_status())


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def my_ui_settings(request: Request) -> Response:
    """Личное оформление: {"theme": "light|dark|auto", "primary": "#RRGGBB"}."""
    user: User = request.user  # type: ignore[assignment]
    try:
        return Response(services.save_ui_settings(user, dict(request.data)))
    except ValueError as error:
        return Response({"non_field_errors": [str(error)]}, status=400)


class SetPinSerializer(serializers.Serializer):  # type: ignore[type-arg]
    password = serializers.CharField(label="Текущий пароль")
    pin = serializers.CharField(label="Новый ПИН")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def set_my_pin(request: Request) -> Response:
    """Сотрудник сам задаёт себе ПИН, подтверждая паролем."""
    data = SetPinSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    user: User = request.user  # type: ignore[assignment]
    if not user.check_password(data.validated_data["password"]):
        return Response({"password": ["Неверный пароль."]}, status=400)
    try:
        services.set_pin(user, data.validated_data["pin"])
    except services.PinError as error:
        return Response({"pin": [str(error)]}, status=400)
    return Response({"has_pin": True})
