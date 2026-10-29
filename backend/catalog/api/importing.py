"""API импорта прайса: шаблон, предпросмотр, загрузка."""

from django.http import HttpResponse
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog import importing


class CanImport(BasePermission):
    """Импорт создаёт и меняет товары — нужны права на добавление и изменение."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        return bool(user and user.has_perms(["catalog.add_item", "catalog.change_item"]))


def _file(request: Request) -> tuple[bytes, str]:
    upload = request.FILES.get("file")
    if upload is None:
        raise ValidationError({"file": ["Выберите файл."]})
    return upload.read(), upload.name or "price.xlsx"


class ImportPreview(APIView):
    """Проверка файла без изменений: что создастся, обновится, какие ошибки."""

    permission_classes = [CanImport]

    def post(self, request: Request) -> Response:
        try:
            return Response(importing.preview(*_file(request)).as_dict())
        except importing.ImportError_ as error:
            raise ValidationError({"file": [str(error)]}) from error


class ImportCommit(APIView):
    """Загрузка прайса: строки с ошибками пропускаются."""

    permission_classes = [CanImport]

    def post(self, request: Request) -> Response:
        try:
            return Response(importing.commit(*_file(request)).as_dict())
        except importing.ImportError_ as error:
            raise ValidationError({"file": [str(error)]}) from error


class ImportTemplate(APIView):
    permission_classes = [CanImport]

    def get(self, request: Request) -> HttpResponse:
        response = HttpResponse(
            importing.template(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="price-template.xlsx"'
        return response
