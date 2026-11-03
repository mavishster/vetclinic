"""Настройки клиники: реквизиты для печатных форм и предельные скидки в счёте."""

from typing import Any

from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core import services
from core.models import Clinic


class ClinicSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    class Meta:
        model = Clinic
        fields = ["id", "name", "address", "phone", "max_discount_goods", "max_discount_services"]
        read_only_fields = ["id"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        for field in ("max_discount_goods", "max_discount_services"):
            if field in attrs and not 0 <= attrs[field] <= 100:
                raise serializers.ValidationError({field: ["Скидка — от 0 до 100 %."]})
        return attrs


class ClinicView(APIView):
    """GET — настройки клиники (видят все сотрудники); PATCH — право «Клиника: изменение»."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(ClinicSerializer(services.current_clinic()).data)

    def patch(self, request: Request) -> Response:
        if not request.user.has_perm("core.change_clinic"):
            return Response({"detail": "Нет права менять настройки клиники."}, status=403)
        data = ClinicSerializer(services.current_clinic(), data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        data.save()
        return Response(data.data)
