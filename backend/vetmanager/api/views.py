"""Перенос из VetManager: проверка связи, что отдаёт API, запуск шагов."""

from typing import Any

from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from vetmanager import client, services, tidy
from vetmanager.models import Imported


class _ImportView(APIView):
    permission_classes = [IsAuthenticated]
    queryset = Imported.objects.none()

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        if not request.user.has_perm("vetmanager.run_import"):
            raise PermissionDenied("Нет права переносить данные из VetManager.")


class StatusView(_ImportView):
    """GET — настроена ли связь и что уже перенесено."""

    def get(self, request: Request) -> Response:
        return Response({"configured": client.is_configured(), "steps": services.status()})


class ProbeView(_ImportView):
    """GET ?model=Good — сколько записей и какие поля отдаёт VetManager.

    Нужно, чтобы сверить перенос с конкретным аккаунтом, не выгружая всё.
    """

    def get(self, request: Request) -> Response:
        model = request.query_params.get("model", "Good")
        if not model.isalnum():
            raise ValidationError({"model": ["Название модели — латиницей, без пробелов."]})
        try:
            return Response(client.sample(model, int(request.query_params.get("count", 2))))
        except client.VetManagerError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error


class DoctorPlanView(_ImportView):
    """GET — кого свяжем с нашими сотрудниками, а кого заведём (до переноса)."""

    def get(self, request: Request) -> Response:
        try:
            plan = services.doctor_rows()
        except services.VetManagerError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        return Response([{key: row[key] for key in row if key != "row"} for row in plan])


class UnitPlanView(_ImportView):
    """GET — что с чем сведётся при переносе единиц: «шт, шт., штука → шт.»."""

    def get(self, request: Request) -> Response:
        try:
            return Response(services.unit_plan())
        except services.VetManagerError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error


class TidyView(_ImportView):
    """Наведение порядка в прайсе после переноса.

    GET — что можно объединить: дубли и фасовки одной позиции.
    POST {"name", "parts": [{"item", "quantity", "unit"}]} — объединить в одну позицию.
    """

    def get(self, request: Request) -> Response:
        return Response(tidy.suggestions())

    def post(self, request: Request) -> Response:
        try:
            item = tidy.merge(str(request.data.get("name") or ""), request.data.get("parts") or [])
        except tidy.catalog.CatalogError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        return Response({"id": str(item.pk), "name": item.name})


class RunStepView(_ImportView):
    """POST {"step": "items"} — выполнить шаг переноса."""

    def post(self, request: Request) -> Response:
        try:
            result = services.run_step(str(request.data.get("step") or ""))
        except services.VetManagerError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        return Response(
            {
                "step": result.step,
                "title": result.title,
                "total": result.total,
                "created": result.created,
                "updated": result.updated,
                "skipped": result.skipped,
                "errors": result.errors[:20],
                "text": result.text,
            }
        )
