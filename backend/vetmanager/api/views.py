"""Перенос из VetManager: проверка связи, что отдаёт API, запуск шагов."""

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from vetmanager import client, reconcile, services, tidy
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
        # Бывают составные адреса: MedicalCards/AllDiagnoses.
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*(/[A-Za-z][A-Za-z0-9]*)*", model):
            raise ValidationError(
                {"model": ["Название раздела — латиницей, без пробелов (можно через «/»)."]}
            )
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
        if request.data.get("skip"):
            try:
                tidy.skip_pair(str(request.data.get("base_name") or ""))
            except tidy.catalog.CatalogError as error:
                raise ValidationError({"non_field_errors": [str(error)]}) from error
            return Response({"skipped": True})
        try:
            item = tidy.merge(str(request.data.get("name") or ""), request.data.get("parts") or [])
        except tidy.catalog.CatalogError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        return Response({"id": str(item.pk), "name": item.name})


class PackagingView(_ImportView):
    """Фасовки препаратов: остаток упаковками, а отпускают поштучно.

    GET — что нужно поправить до переноса счетов.
    POST {"item", "quantity", "inside", "price"} — перевести позицию на поштучный учёт.
    """

    def get(self, request: Request) -> Response:
        return Response(tidy.packaging_rows())

    def post(self, request: Request) -> Response:
        data = request.data
        if data.get("skip"):
            try:
                tidy.skip_packaging(str(data.get("item") or ""))
            except tidy.catalog.CatalogError as error:
                raise ValidationError({"non_field_errors": [str(error)]}) from error
            return Response({"skipped": True})
        try:
            price = data.get("price")
            item = tidy.set_packaging(
                str(data.get("item") or ""),
                Decimal(str(data.get("quantity") or "0")),
                str(data.get("inside") or ""),
                Decimal(str(price)) if price not in (None, "") else None,
            )
        except (InvalidOperation, ValueError) as error:
            raise ValidationError({"quantity": ["Укажите количество числом."]}) from error
        except tidy.catalog.CatalogError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        return Response({"id": str(item.pk), "name": item.name, "base_unit": item.base_unit.name})


class ReconcileView(_ImportView):
    """GET — сверка переноса: сколько записей в VetManager, сколько у нас, чего нет."""

    def get(self, request: Request) -> Response:
        return Response(reconcile.report())


class RunStepView(_ImportView):
    """POST {"step": "items"} — выполнить шаг переноса.

    {"replace": true} для медкарт — перенести заново: перенесённые записи убираются
    и переносятся снова (нужно, когда перенос улучшили).
    """

    def post(self, request: Request) -> Response:
        try:
            result = services.run_step(
                str(request.data.get("step") or ""), bool(request.data.get("replace"))
            )
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
                "kept": result.kept[:50],
                "kept_total": len(result.kept),
                "text": result.text,
            }
        )
