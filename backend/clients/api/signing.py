"""API подписи на планшете: планшеты, отправка документа, экран планшета, подпись."""

from typing import Any

from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from clients import services
from clients.models import SignatureRequest, SigningStation
from core.api.directories import DirectoryViewSet
from core.models import PrintTemplate


class SigningStationViewSet(DirectoryViewSet):
    model = SigningStation
    extra_fields = ("user",)


class SignatureRequestSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    template = serializers.PrimaryKeyRelatedField(
        queryset=PrintTemplate.objects.filter(kind="client_document"), write_only=True
    )
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    station_name = serializers.CharField(source="station.name", read_only=True)

    class Meta:
        model = SignatureRequest
        fields = [
            "id",
            "client",
            "station",
            "station_name",
            "template",
            "title",
            "purpose",
            "contract",
            "status",
            "status_label",
            "created_at",
            "signed_at",
            "expires_at",
            "result",
        ]
        read_only_fields = ["title", "status", "created_at", "signed_at", "expires_at", "result"]

    def create(self, validated_data: dict[str, Any]) -> SignatureRequest:
        try:
            return services.send_for_signature(
                validated_data["client"],
                validated_data["template"],
                validated_data["station"],
                self.context["request"].user,
                validated_data.get("purpose", "other"),
                validated_data.get("contract"),
            )
        except services.SigningError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error


class SignatureRequestViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]
    """Документы на подпись.

    Отправить — POST; статус — GET /{id}/; отменить — POST /{id}/cancel/.
    """

    serializer_class = SignatureRequestSerializer
    queryset = SignatureRequest.objects.select_related("station")
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self) -> QuerySet[SignatureRequest]:
        queryset = SignatureRequest.objects.select_related("station")
        if client := self.request.query_params.get("client"):
            queryset = queryset.filter(client=client)
        return queryset

    @action(detail=False, methods=["get"])
    def templates(self, request: Request) -> Response:
        """Документы, которые можно отправить на подпись (печатные формы «Документ клиента»)."""
        found = PrintTemplate.objects.filter(kind="client_document", is_active=True).order_by(
            "name"
        )
        return Response([{"id": str(t.pk), "name": t.name} for t in found])

    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        signature = self.get_object()
        services.cancel_signature(signature)
        return Response(self.get_serializer(signature).data)


class _StationView(APIView):
    """Экран планшета: только учётная запись планшета с правом «подписывать на планшете»."""

    permission_classes = [IsAuthenticated]

    def station(self, request: Request) -> SigningStation:
        if not request.user.has_perm("clients.sign_on_station"):
            raise PermissionDenied("Это экран для планшета подписи.")
        station = services.station_of(request.user)
        if station is None:
            raise PermissionDenied("Учётная запись не привязана к планшету подписи.")
        return station


class StationCurrentView(_StationView):
    """GET — документ, ждущий подписи на этом планшете (или пусто)."""

    def get(self, request: Request) -> Response:
        station = self.station(request)
        pending = services.pending_for(station)
        if pending is None:
            return Response({"station": station.name})
        return Response(
            {
                "station": station.name,
                "id": str(pending.pk),
                "title": pending.title,
                "client_name": pending.client.full_name,
                "html": pending.html,
            }
        )


class StationSignView(_StationView):
    """POST {"id": "...", "signature": "data:image/png;base64,..."} — подписать."""

    def post(self, request: Request) -> Response:
        station = self.station(request)
        signature = get_object_or_404(SignatureRequest, pk=request.data.get("id"))
        agent = request.META.get("HTTP_USER_AGENT", "")[:200]
        source = f"{request.META.get('REMOTE_ADDR', '')} · {agent}"
        try:
            services.sign(signature, station, str(request.data.get("signature") or ""), source)
        except services.SigningError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        return Response({"status": "signed"})
