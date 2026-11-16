"""Настройки клиники: реквизиты для печатных форм и предельные скидки в счёте."""

from typing import Any

from django.http import HttpResponse
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core import services
from core.models import Clinic


class ClinicSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    # Есть ли логотип и его «версия» — чтобы браузер не показывал старую картинку из кэша.
    logo_version = serializers.SerializerMethodField()

    def get_logo_version(self, clinic: Clinic) -> str | None:
        return services.clinic_logo_version(clinic)

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
            "qr_base_url",
            "qr_size_mm",
            "qr_label_width_mm",
            "qr_label_height_mm",
            "qr_fields",
            "logo_version",
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
        self._validate_qr(attrs)
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

    def _validate_qr(self, attrs: dict[str, Any]) -> None:
        if url := attrs.get("qr_base_url", "").strip():
            if not url.lower().startswith(("http://", "https://")) or " " in url:
                raise serializers.ValidationError(
                    {"qr_base_url": ["Адрес — вида http://192.168.0.10 или https://vet.clinic.kg."]}
                )
            attrs["qr_base_url"] = url.rstrip("/")
        if "qr_size_mm" in attrs and not 15 <= attrs["qr_size_mm"] <= 120:
            raise serializers.ValidationError({"qr_size_mm": ["QR-код — от 15 до 120 мм."]})
        for field in ("qr_label_width_mm", "qr_label_height_mm"):
            if field in attrs and not 40 <= attrs[field] <= 200:
                raise serializers.ValidationError({field: ["Этикетка — от 40 до 200 мм."]})
        fields = attrs.get("qr_fields")
        if fields is not None and (
            not isinstance(fields, list)
            or len(fields) > 30
            or not all(isinstance(f, str) and len(f) <= 40 for f in fields)
        ):
            raise serializers.ValidationError({"qr_fields": ["Ожидается список полей."]})
        size = attrs.get("qr_size_mm", self.instance and self.instance.qr_size_mm)
        width = attrs.get("qr_label_width_mm", self.instance and self.instance.qr_label_width_mm)
        if size and width and size + 8 > width:
            raise serializers.ValidationError(
                {"qr_size_mm": ["QR-код должен помещаться в этикетку по ширине (с полями 4 мм)."]}
            )


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


class ClinicLogoView(APIView):
    """Логотип клиники.

    GET — картинка PNG (открыт без входа: логотип виден на экране входа);
    логотип не загружен — 204 (это не ошибка: клиника может работать без логотипа).
    POST (multipart: file) — загрузить, DELETE — убрать; право «Клиника: изменение».
    """

    parser_classes = [MultiPartParser]

    def get_permissions(self):  # type: ignore[no-untyped-def]
        return [AllowAny()] if self.request.method == "GET" else [IsAuthenticated()]

    def get(self, request: Request) -> HttpResponse:
        data = services.clinic_logo_bytes()
        if data is None:
            return HttpResponse(status=204)
        response = HttpResponse(data, content_type="image/png")
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "public, max-age=300"
        return response

    def _require_change(self, request: Request) -> None:
        if not request.user.has_perm("core.change_clinic"):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Нет права менять настройки клиники.")

    def post(self, request: Request) -> Response:
        self._require_change(request)
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": ["Выберите картинку."]})
        try:
            clinic = services.set_clinic_logo(upload)
        except services.LogoError as error:
            raise ValidationError({"file": [str(error)]}) from error
        return Response(ClinicSerializer(clinic).data)

    def delete(self, request: Request) -> Response:
        self._require_change(request)
        return Response(ClinicSerializer(services.remove_clinic_logo()).data)
