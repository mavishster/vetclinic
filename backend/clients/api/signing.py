"""API подписи на планшете: планшеты, отправка документа, экран планшета, подпись."""

from typing import Any

from django.db.models import Q, QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from clients import services
from clients.models import PhotoRequest, SignatureRequest, SigningStation
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
    client_name = serializers.CharField(source="client.full_name", read_only=True)
    purpose_label = serializers.CharField(source="get_purpose_display", read_only=True)
    sent_by_name = serializers.SerializerMethodField()

    class Meta:
        model = SignatureRequest
        fields = [
            "id",
            "client",
            "client_name",
            "purpose_label",
            "sent_by_name",
            "content_hash",
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
        read_only_fields = [
            "title",
            "status",
            "created_at",
            "signed_at",
            "expires_at",
            "result",
            "content_hash",
        ]

    def get_sent_by_name(self, request: SignatureRequest) -> str:
        user = request.sent_by
        return (user.short_name or user.username) if user else ""

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
        """Фильтры журнала «Подписанные документы»: ?client=, ?status=signed|pending|cancelled,
        ?purpose=contract|consent|other, ?from=&to= (дата отправки), ?search= (клиент, документ)."""
        queryset = SignatureRequest.objects.select_related("station", "client", "sent_by")
        params = self.request.query_params
        if client := params.get("client"):
            queryset = queryset.filter(client=client)
        if status := params.get("status"):
            queryset = queryset.filter(status=status)
        if purpose := params.get("purpose"):
            queryset = queryset.filter(purpose=purpose)
        if date_from := params.get("from"):
            queryset = queryset.filter(created_at__date__gte=date_from)
        if date_to := params.get("to"):
            queryset = queryset.filter(created_at__date__lte=date_to)
        for word in params.get("search", "").split():
            queryset = queryset.filter(
                Q(client__last_name__icontains=word)
                | Q(client__first_name__icontains=word)
                | Q(client__middle_name__icontains=word)
                | Q(title__icontains=word)
            )
        return queryset.order_by("-created_at")

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Журнал — последние 500 документов по фильтрам (новые сверху)."""
        rows = self.filter_queryset(self.get_queryset())[:500]
        return Response(self.get_serializer(rows, many=True).data)

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
    """GET — задание для этого планшета: документ на подпись или снимок (или пусто)."""

    def get(self, request: Request) -> Response:
        station = self.station(request)
        photo = services.pending_photo_for(station)
        if photo is not None:
            return Response(
                {
                    "station": station.name,
                    "task": "photo",
                    "id": str(photo.pk),
                    "client_name": photo.client.full_name,
                }
            )
        pending = services.pending_for(station)
        if pending is None:
            return Response({"station": station.name})
        return Response(
            {
                "station": station.name,
                "task": "sign",
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


class StationPhotoView(_StationView):
    """POST multipart {id, file} — снимок, сделанный камерой планшета."""

    parser_classes = [MultiPartParser]

    def post(self, request: Request) -> Response:
        station = self.station(request)
        photo = get_object_or_404(PhotoRequest, pk=request.data.get("id"))
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": ["Нет снимка."]})
        try:
            services.take_photo_on_station(photo, station, upload)
        except services.SigningError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        return Response({"status": "done"})


class PhotoRequestSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    station_name = serializers.CharField(source="station.name", read_only=True)

    class Meta:
        model = PhotoRequest
        fields = ["id", "client", "station", "station_name", "status", "result", "created_at"]
        read_only_fields = ["status", "result", "created_at"]


class PhotoRequestViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]
    """Снимок на планшете: запросить (POST), статус (GET /{id}/), отменить (POST /{id}/cancel/).

    Права — как на изменение клиента: фото — часть его карточки.
    """

    serializer_class = PhotoRequestSerializer
    queryset = PhotoRequest.objects.select_related("station")
    http_method_names = ["get", "post", "head", "options"]
    permission_classes = [IsAuthenticated]

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        if not request.user.has_perm("clients.change_client"):
            raise PermissionDenied("Нет права изменять карточку клиента.")

    def perform_create(self, serializer: Any) -> None:
        data = serializer.validated_data
        try:
            serializer.instance = services.request_photo(
                data["client"], data["station"], self.request.user
            )
        except services.ClientError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error

    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        photo = self.get_object()
        services.cancel_photo(photo)
        return Response(self.get_serializer(photo).data)
