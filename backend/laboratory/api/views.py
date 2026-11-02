"""API лаборатории: приём результатов с приборов, результаты, привязка, динамика."""

import hmac
from typing import Any

from django.conf import settings
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.directories import DirectoryViewSet
from laboratory import services
from laboratory.models import Analyte, LabResult, LabValue
from medical import services as medical


class AnalyteViewSet(DirectoryViewSet):
    model = Analyte
    extra_fields = ("code", "unit", "group")


class ValueSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    class Meta:
        model = LabValue
        fields = ["id", "analyte", "name", "value", "numeric", "unit", "reference", "flag"]


class ResultSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    values = ValueSerializer(many=True, read_only=True)
    pet_name = serializers.CharField(source="pet.name", read_only=True, default="")
    visit_lab_code = serializers.IntegerField(source="visit.lab_code", read_only=True, default=None)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    abnormal = serializers.SerializerMethodField()

    class Meta:
        model = LabResult
        fields = [
            "id",
            "visit",
            "visit_lab_code",
            "pet",
            "pet_name",
            "device",
            "analysis",
            "code_entered",
            "received_at",
            "status",
            "status_label",
            "values",
            "abnormal",
        ]

    def get_abnormal(self, result: LabResult) -> int:
        return sum(v.flag in {"high", "low", "positive"} for v in result.values.all())


class ResultViewSet(viewsets.ReadOnlyModelViewSet):  # type: ignore[type-arg]
    """Результаты анализов: ?visit=, ?pet=, ?status=unassigned.

    POST /{id}/assign/ {"lab_code": 1043} — привязать к записи медкарты по номеру.
    GET /history/?pet=&analyte= — динамика показателя.
    """

    serializer_class = ResultSerializer
    queryset = LabResult.objects.all()

    def get_queryset(self) -> QuerySet[LabResult]:
        params = self.request.query_params
        return services.results(
            visit=params.get("visit") or None,
            pet=params.get("pet") or None,
            status=params.get("status") or None,
        )[:300]

    def get_object(self) -> LabResult:
        result = get_object_or_404(LabResult, pk=self.kwargs["pk"])
        self.check_object_permissions(self.request, result)
        return result

    @action(detail=True, methods=["post"])
    def assign(self, request: Request, pk: str | None = None) -> Response:
        visit = medical.visit_by_lab_code(request.data.get("lab_code", ""))
        if visit is None:
            raise ValidationError({"lab_code": ["Запись медкарты с таким номером не найдена."]})
        result = services.assign(self.get_object(), visit)
        return Response(self.get_serializer(result).data)

    @action(detail=False, methods=["get"])
    def history(self, request: Request) -> Response:
        pet, analyte = request.query_params.get("pet"), request.query_params.get("analyte")
        if not pet or not analyte:
            raise ValidationError({"pet": ["Укажите питомца и показатель."]})
        rows = services.history(pet, analyte)
        return Response(
            [
                {**r, "numeric": str(r["numeric"]) if r["numeric"] is not None else None}
                for r in rows
            ]
        )

    @action(detail=False, methods=["get"], url_path="unassigned-count")
    def unassigned_count(self, request: Request) -> Response:
        return Response({"count": services.unassigned_count()})


class IngestView(APIView):
    """Приём результатов от LabService (или другого шлюза приборов).

    Заголовок X-Lab-Token — ключ из настройки LAB_API_TOKEN. Тело:
    {"device": "...", "analysis": "...", "code": "1043", "message_id": "...",
     "values": [{"code": "WBC", "name": "...", "value": "18.2", "unit": "10^9/L",
                 "reference": "4.0-15.0", "flag": "H"}]}
    """

    authentication_classes: list[Any] = []
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        expected = getattr(settings, "LAB_API_TOKEN", "")
        given = request.headers.get("X-Lab-Token", "")
        if not expected:
            return Response(
                {"detail": "Приём анализов не настроен: задайте LAB_API_TOKEN."}, status=503
            )
        if not hmac.compare_digest(given, expected):
            return Response({"detail": "Неверный ключ."}, status=status.HTTP_403_FORBIDDEN)
        data = request.data
        values = data.get("values") or []
        if not isinstance(values, list):
            raise ValidationError({"values": ["Ожидается список показателей."]})
        try:
            result = services.ingest(
                str(data.get("device") or "Прибор"),
                str(data.get("analysis") or ""),
                str(data.get("code") or ""),
                values,
                str(data.get("message_id") or ""),
            )
        except services.LabError as error:
            raise ValidationError({"values": [str(error)]}) from error
        return Response(
            {
                "id": str(result.pk),
                "status": result.status,
                "visit_lab_code": result.visit.lab_code if result.visit else None,
            },
            status=201,
        )
