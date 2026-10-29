"""Вход и выход через API (сессия Django + защита CSRF)."""

from django.contrib.auth import authenticate, login, logout
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response


class LoginSerializer(serializers.Serializer):  # type: ignore[type-arg]
    username = serializers.CharField(label="Логин")
    password = serializers.CharField(label="Пароль")


@api_view(["GET"])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def csrf(request: Request) -> Response:
    """Выдаёт cookie csrftoken — интерфейс запрашивает её перед входом."""
    return Response({"ok": True})


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request: Request) -> Response:
    data = LoginSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    user = authenticate(
        request._request,
        username=data.validated_data["username"],
        password=data.validated_data["password"],
    )
    if user is None:
        return Response({"detail": "Неверный логин или пароль."}, status=400)
    login(request._request, user)
    return Response({"ok": True})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request: Request) -> Response:
    logout(request._request)
    return Response({"ok": True})
