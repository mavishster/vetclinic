"""API стационара: палаты, госпитализации, назначения, лист назначений, наблюдения."""

from datetime import date
from typing import Any

from django.db.models import QuerySet
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core import services as core
from core.api.directories import DirectoryViewSet
from core.api.permissions import require_special
from core.models import PrintTemplate
from inpatient import qr, services
from inpatient.models import Hospitalization, Observation, TreatmentPlan, TreatmentTask, Ward


class WardViewSet(DirectoryViewSet):
    model = Ward
    extra_fields = ("kind", "places", "daily_item")


class TaskSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    title = serializers.CharField(source="plan.title", read_only=True)
    dose = serializers.CharField(source="plan.dose", read_only=True)
    route_label = serializers.CharField(source="plan.get_route_display", read_only=True)
    done_by_name = serializers.SerializerMethodField()
    overdue = serializers.SerializerMethodField()

    def get_done_by_name(self, task: TreatmentTask) -> str:
        user = task.done_by
        return (user.short_name or user.username) if user else ""

    class Meta:
        model = TreatmentTask
        fields = [
            "id",
            "plan",
            "title",
            "dose",
            "route_label",
            "scheduled_at",
            "due_until",
            "status",
            "done_at",
            "done_by_name",
            "note",
            "quantity",
            "overdue",
        ]

    def get_overdue(self, task: TreatmentTask) -> bool:
        return task.is_overdue(timezone.now())


class PlanSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    route_label = serializers.CharField(source="get_route_display", read_only=True)

    class Meta:
        model = TreatmentPlan
        fields = [
            "id",
            "item",
            "title",
            "dose",
            "route",
            "route_label",
            "times",
            "start_date",
            "days",
            "note",
            "is_active",
        ]
        read_only_fields = ["is_active"]
        extra_kwargs = {"title": {"required": False, "allow_blank": True}}


class ObservationSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    author_name = serializers.CharField(source="author.short_name", read_only=True, default="")

    class Meta:
        model = Observation
        fields = ["id", "at", "temperature", "weight", "pulse", "note", "author_name"]
        extra_kwargs = {"at": {"required": False}}


class HospitalizationSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    pet_name = serializers.CharField(source="pet.name", read_only=True)
    species = serializers.CharField(source="pet.species.name", read_only=True)
    client_name = serializers.CharField(source="client.full_name", read_only=True)
    ward_name = serializers.CharField(source="ward.name", read_only=True)
    doctor_name = serializers.CharField(source="doctor.short_name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    days = serializers.SerializerMethodField()
    last_observation = serializers.SerializerMethodField()
    tasks_today = serializers.SerializerMethodField()
    staff_names = serializers.SerializerMethodField()
    cage = serializers.SerializerMethodField()

    class Meta:
        model = Hospitalization
        fields = [
            "id",
            "pet",
            "pet_name",
            "species",
            "client",
            "client_name",
            "ward",
            "ward_name",
            "place",
            "doctor",
            "doctor_name",
            "visit",
            "admitted_at",
            "planned_discharge",
            "discharged_at",
            "reason",
            "outcome",
            "status",
            "status_label",
            "invoice_id",
            "days",
            "last_observation",
            "tasks_today",
            "staff",
            "staff_names",
            "cage",
        ]
        read_only_fields = [
            "client",
            "admitted_at",
            "discharged_at",
            "status",
            "invoice_id",
            "outcome",
        ]

    def get_cage(self, h: Hospitalization) -> dict[str, str] | None:
        """Данные экрана «у клетки» — только при открытии карточки (в списке не нужны).
        Телефон владельца — только тем, у кого есть право на просмотр клиентов."""
        view = self.context.get("view")
        if getattr(view, "action", None) != "retrieve":
            return None
        card = qr.cage_card(h)
        request = self.context.get("request")
        phone = (
            h.client.phones.first()
            if request and request.user.has_perm("clients.view_client")
            else None
        )
        card["owner_phone"] = phone.number if phone else ""
        return card

    def get_staff_names(self, h: Hospitalization) -> list[str]:
        return [u.short_name or u.username for u in h.staff.all()]

    def get_days(self, h: Hospitalization) -> int:
        return services.days_count(h)

    def get_last_observation(self, h: Hospitalization) -> dict[str, Any] | None:
        last = h.observations.first()
        return ObservationSerializer(last).data if last else None

    def get_tasks_today(self, h: Hospitalization) -> dict[str, int]:
        tasks = list(services.sheet(h, timezone.localdate()))
        now = timezone.now()
        return {
            "total": len(tasks),
            "done": sum(t.status == "done" for t in tasks),
            "overdue": sum(t.is_overdue(now) for t in tasks),
        }

    def create(self, validated_data: dict[str, Any]) -> Hospitalization:
        try:
            return services.admit(
                validated_data["pet"],
                validated_data["ward"],
                validated_data["doctor"],
                validated_data.get("reason", ""),
                validated_data.get("visit"),
                validated_data.get("place"),
                validated_data.get("planned_discharge"),
                validated_data.get("staff"),
            )
        except services.InpatientError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error


class HospitalizationViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]
    """Госпитализации. ?status=active (по умолчанию) | discharged | all; ?pet=."""

    serializer_class = HospitalizationSerializer
    queryset = Hospitalization.objects.all()
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self) -> QuerySet[Hospitalization]:
        queryset = Hospitalization.objects.select_related(
            "pet__species", "client", "ward", "doctor"
        ).prefetch_related("staff")
        # Карточка по ссылке (например, из QR) открывается и у выписанного пациента.
        if self.kwargs.get("pk"):
            return queryset
        params = self.request.query_params
        if pet := params.get("pet"):
            return queryset.filter(pet=pet)
        status = params.get("status", "active")
        return queryset if status == "all" else queryset.filter(status=status)

    def _error(self, error: Exception) -> ValidationError:
        return ValidationError({"non_field_errors": [str(error)]})

    def _day(self, request: Request) -> date:
        try:
            return date.fromisoformat(
                request.query_params.get("date") or timezone.localdate().isoformat()
            )
        except ValueError:
            raise ValidationError({"date": ["Дата в формате ГГГГ-ММ-ДД."]}) from None

    @action(detail=False, methods=["get"], url_path="my-tasks")
    def my_tasks(self, request: Request) -> Response:
        """Пора выполнить: просроченные и на ближайшие 30 минут — у моих пациентов
        (?all=1 — у всех пациентов стационара)."""
        everyone = request.query_params.get("all") == "1"
        tasks = services.my_tasks(request.user, everyone)
        now = timezone.now()
        return Response(
            [
                {
                    "id": t.pk,
                    "hospitalization": str(t.hospitalization_id),
                    "pet_name": t.hospitalization.pet.name,
                    "ward": t.hospitalization.ward.name,
                    "place": t.hospitalization.place,
                    "title": t.plan.title,
                    "dose": t.plan.dose,
                    "route_label": t.plan.get_route_display(),
                    "scheduled_at": t.scheduled_at,
                    "due_until": t.due_until,
                    "overdue": t.is_overdue(now),
                }
                for t in tasks
            ]
        )

    @action(detail=True, methods=["get"])
    def sheet(self, request: Request, pk: str | None = None) -> Response:
        """Лист назначений на день: ?date=."""
        h = self.get_object()
        return Response(TaskSerializer(services.sheet(h, self._day(request)), many=True).data)

    @action(detail=True, methods=["get", "post"])
    def plans(self, request: Request, pk: str | None = None) -> Response:
        h = self.get_object()
        if request.method == "POST":
            data = PlanSerializer(data=request.data)
            data.is_valid(raise_exception=True)
            v = data.validated_data
            try:
                services.add_plan(
                    h,
                    v.get("title", ""),
                    v.get("times", []),
                    v["start_date"],
                    v.get("days", 1),
                    v.get("item"),
                    v.get("dose", ""),
                    v.get("route", "oral"),
                    v.get("note", ""),
                )
            except services.InpatientError as error:
                raise self._error(error) from error
        return Response(PlanSerializer(h.plans.all(), many=True).data)

    @action(detail=True, methods=["post"], url_path=r"plans/(?P<plan_id>[^/.]+)/stop")
    def stop_plan(
        self, request: Request, pk: str | None = None, plan_id: str | None = None
    ) -> Response:
        h = self.get_object()
        services.stop_plan(get_object_or_404(TreatmentPlan, pk=plan_id, hospitalization=h))
        return Response(PlanSerializer(h.plans.all(), many=True).data)

    @action(detail=True, methods=["post"], url_path=r"tasks/(?P<task_id>[^/.]+)/mark")
    def mark(self, request: Request, pk: str | None = None, task_id: str | None = None) -> Response:
        """Отметка в листе назначений: {"status": "done|skipped|planned", "note", "quantity"}."""
        h = self.get_object()
        task = get_object_or_404(TreatmentTask, pk=task_id, hospitalization=h)
        quantity = request.data.get("quantity")
        try:
            services.mark_task(
                task,
                request.data.get("status", ""),
                request.user,
                request.data.get("note", ""),
                None if quantity in (None, "") else quantity,
            )
        except services.InpatientError as error:
            raise self._error(error) from error
        return Response(TaskSerializer(task).data)

    @action(detail=True, methods=["get", "post"])
    def observations(self, request: Request, pk: str | None = None) -> Response:
        h = self.get_object()
        if request.method == "POST":
            data = ObservationSerializer(data=request.data)
            data.is_valid(raise_exception=True)
            try:
                services.add_observation(h, request.user, **data.validated_data)
            except services.InpatientError as error:
                raise self._error(error) from error
        return Response(
            ObservationSerializer(h.observations.select_related("author"), many=True).data
        )

    @action(detail=True, methods=["post"], url_path="import-from-visit")
    def import_from_visit(self, request: Request, pk: str | None = None) -> Response:
        h = self.get_object()
        try:
            count = services.import_from_visit(h)
        except services.InpatientError as error:
            raise self._error(error) from error
        return Response({"imported": count})

    @action(detail=True, methods=["post"])
    def discharge(self, request: Request, pk: str | None = None) -> Response:
        h = self.get_object()
        try:
            services.discharge(h, request.data.get("outcome", ""))
        except services.InpatientError as error:
            raise self._error(error) from error
        return Response(self.get_serializer(h).data)

    @action(detail=True, methods=["post"])
    def invoice(self, request: Request, pk: str | None = None) -> Response:
        """Черновик счёта за стационар — откроется для проверки и оплаты."""
        h = self.get_object()
        try:
            invoice_id = services.create_invoice(h)
        except services.InpatientError as error:
            raise self._error(error) from error
        return Response({"invoice": str(invoice_id)})

    @action(detail=True, methods=["get"], url_path="print-sheet")
    def print_sheet(self, request: Request, pk: str | None = None) -> HttpResponse:
        h = self.get_object()
        template = (
            PrintTemplate.objects.filter(kind="treatment_sheet", is_active=True)
            .order_by("name")
            .first()
        )
        if template is None:
            raise ValidationError({"template": ["Нет печатной формы «Лист назначений»."]})
        pdf = core.render_print(template, services.sheet_context(h, self._day(request)))
        return HttpResponse(pdf, content_type="application/pdf")

    def _qr_pdf(self, request: Request, items: list[tuple[Hospitalization, int]]) -> HttpResponse:
        require_special(request, "inpatient.print_qr")
        template = (
            PrintTemplate.objects.filter(kind="hospitalization_qr", is_active=True)
            .order_by("name")
            .first()
        )
        if template is None:
            raise ValidationError({"template": ["Нет печатной формы «QR-этикетка пациента»."]})
        if not items:
            raise ValidationError({"ids": ["Нет пациентов для печати."]})
        context = qr.sheet_context(items, request.build_absolute_uri("/"))
        return HttpResponse(core.render_print(template, context), content_type="application/pdf")

    @staticmethod
    def _copies(request: Request) -> int:
        try:
            return max(1, min(int(request.query_params.get("copies", 1)), qr.MAX_COPIES))
        except ValueError:
            return 1

    @action(detail=True, methods=["get"], url_path="qr-label")
    def qr_label(self, request: Request, pk: str | None = None) -> HttpResponse:
        """PDF с QR-этикеткой пациента (лист А4, этикетки для вырезания): ?copies=1…8."""
        return self._qr_pdf(request, [(self.get_object(), self._copies(request))])

    @action(detail=False, methods=["get"], url_path="qr-labels")
    def qr_labels(self, request: Request) -> HttpResponse:
        """PDF с этикетками нескольких пациентов: ?ids=a,b,c; без ids — все в стационаре."""
        ids = [i for i in request.query_params.get("ids", "").split(",") if i]
        queryset = self.get_queryset().filter(status="active")
        if ids:
            queryset = queryset.filter(pk__in=ids)
        return self._qr_pdf(request, [(h, 1) for h in queryset.order_by("ward__name", "place")])


class CanConfigureQr(BasePermission):
    """Перечень полей нужен тем, кто настраивает этикетку или печатает её."""

    def has_permission(self, request: Request, view: Any) -> bool:
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (user.has_perm("core.change_clinic") or user.has_perm("inpatient.print_qr"))
        )


class QrFieldsView(APIView):
    """Какие поля можно выводить на QR-этикетке — для настройки в администрировании."""

    permission_classes = [CanConfigureQr]

    def get(self, request: Request) -> Response:
        return Response(qr.available_fields())
