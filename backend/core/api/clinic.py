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
        fields = [
            "id",
            "name",
            "address",
            "phone",
            "max_discount_goods",
            "max_discount_services",
            "department_issue_days",
            "department_count_from_days",
            "department_count_due_days",
        ]
        read_only_fields = ["id"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        for field in ("max_discount_goods", "max_discount_services"):
            if field in attrs and not 0 <= attrs[field] <= 100:
                raise serializers.ValidationError({field: ["Скидка — от 0 до 100 %."]})
        for field in (
            "department_issue_days",
            "department_count_from_days",
            "department_count_due_days",
        ):
            if attrs.get(field, 0) > 365:
                raise serializers.ValidationError({field: ["Не больше 365 дней."]})
        start = attrs.get(
            "department_count_from_days", self.instance and self.instance.department_count_from_days
        )
        due = attrs.get(
            "department_count_due_days", self.instance and self.instance.department_count_due_days
        )
        if start and due and start > due:
            raise serializers.ValidationError(
                {"department_count_from_days": ["«Через» не может быть больше, чем «не позже»."]}
            )
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
