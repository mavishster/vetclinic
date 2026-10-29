"""API файлов: список файлов записи, загрузка, переименование, скачивание, удаление."""

from typing import Any

from django.db.models import QuerySet
from django.http import FileResponse
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from core import attachments
from core.api.directories import DirectoryViewSet
from core.models import Attachment, FileCategory


class AttachmentSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    category_name = serializers.CharField(source="category.name", read_only=True, default="")
    author = serializers.CharField(source="created_by.short_name", read_only=True, default="")

    class Meta:
        model = Attachment
        fields = [
            "id", "name", "category", "category_name", "size", "content_type",
            "author", "created_at",
        ]  # fmt: skip
        read_only_fields = ["size", "content_type", "created_at"]


class AttachmentViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]
    """Файлы записи: ?owner_type=clients.client&owner_id=<id> (обязательно), ?category=.

    Загрузка — multipart: file, owner_type, owner_id, category (необязательно), name.
    """

    serializer_class = AttachmentSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    queryset = Attachment.objects.all()

    def get_queryset(self) -> QuerySet[Attachment]:
        queryset = Attachment.objects.select_related("category", "created_by")
        if self.action != "list":
            return queryset
        params = self.request.query_params
        owner_type, owner_id = params.get("owner_type"), params.get("owner_id")
        if not owner_type or not owner_id:
            raise ValidationError({"owner": ["Укажите owner_type и owner_id."]})
        try:
            queryset = queryset.filter(
                owner_type=attachments.owner_content_type(owner_type), owner_id=owner_id
            )
        except attachments.AttachmentError as error:
            raise ValidationError({"owner": [str(error)]}) from error
        if category := params.get("category"):
            queryset = queryset.filter(category=category)
        return queryset

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        file = request.FILES.get("file")
        if file is None:
            raise ValidationError({"file": ["Выберите файл."]})
        category_id = request.data.get("category") or None
        category = FileCategory.objects.filter(pk=category_id).first() if category_id else None
        try:
            attachment = attachments.attach(
                request.data.get("owner_type", ""),
                request.data.get("owner_id"),
                file,
                name=request.data.get("name", ""),
                category=category,
            )
        except attachments.AttachmentError as error:
            raise ValidationError({"file": [str(error)]}) from error
        return Response(self.get_serializer(attachment).data, status=201)

    @action(detail=True, methods=["get"])
    def download(self, request: Request, pk: str | None = None) -> FileResponse:
        """Файл: картинки и PDF открываются в браузере, ?download=1 — скачать."""
        attachment = self.get_object()
        return FileResponse(
            attachment.file.open("rb"),
            as_attachment=request.query_params.get("download") == "1",
            filename=attachment.name,
            content_type=attachment.content_type or None,
        )


class FileCategoryViewSet(DirectoryViewSet):
    model = FileCategory
