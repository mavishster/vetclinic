"""API календаря: цели обращения, записи на приём, день календаря."""

from datetime import date
from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from clients.models import Client
from core.api.directories import DirectoryViewSet
from scheduling import services
from scheduling.models import Appointment, VisitPurpose
from staff import services as staff


class PurposeViewSet(DirectoryViewSet):
    model = VisitPurpose
    extra_fields = ("kind", "duration_minutes", "color", "show_in_portal")


class QuickClientSerializer(serializers.Serializer):  # type: ignore[type-arg]
    last_name = serializers.CharField()
    first_name = serializers.CharField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(required=False, allow_blank=True, default="")


class AppointmentSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    client = serializers.PrimaryKeyRelatedField(queryset=Client.objects.all(), required=False)
    new_client = QuickClientSerializer(write_only=True, required=False)
    end = serializers.DateTimeField(required=False)
    client_name = serializers.CharField(source="client.full_name", read_only=True)
    client_status = serializers.CharField(source="client.status", read_only=True)
    client_phone = serializers.SerializerMethodField()
    pet_name = serializers.SerializerMethodField()
    doctor_name = serializers.CharField(source="doctor.short_name", read_only=True, default="")
    purpose_name = serializers.CharField(source="purpose.name", read_only=True, default="")
    purpose_color = serializers.CharField(source="purpose.color", read_only=True, default="")
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        fields = [
            "id", "client", "new_client", "client_name", "client_status", "client_phone",
            "pet", "pet_note", "pet_name", "doctor", "doctor_name", "purpose", "purpose_name",
            "purpose_color", "start", "end", "status", "status_label", "source", "note",
            "arrived_at", "started_at", "completed_at", "cancel_reason", "is_overdue",
        ]  # fmt: skip
        read_only_fields = [
            "status", "arrived_at", "started_at", "completed_at", "cancel_reason",
        ]  # fmt: skip

    def get_client_phone(self, appointment: Appointment) -> str:
        phone = appointment.client.phones.order_by("-is_primary").first()
        return phone.number if phone else ""

    def get_pet_name(self, appointment: Appointment) -> str:
        return appointment.pet.name if appointment.pet else appointment.pet_note

    def get_is_overdue(self, appointment: Appointment) -> bool:
        return services.is_overdue(appointment)

    def _save(self, appointment: Appointment, data: dict[str, Any]) -> Appointment:
        quick = data.pop("new_client", None)
        for field, value in data.items():
            setattr(appointment, field, value)
        force = str(self.context["request"].query_params.get("force", "")).lower() in {"1", "true"}
        if "end" not in data or data.get("end") is None:
            appointment.end = services.default_end(appointment.start, appointment.purpose)
        try:
            with transaction.atomic():
                if quick:
                    # Сначала предупреждения — чтобы не завести временного клиента зря.
                    if not force and (warnings := services.check_appointment(appointment)):
                        raise services.AppointmentWarning(warnings)
                    appointment.client = services.quick_client(**quick)
                    force = True  # предупреждения уже показаны или их нет
                if not appointment.client_id:
                    raise services.AppointmentError("Выберите клиента или заведите нового.")
                return services.save_appointment(appointment, force=force)
        except services.AppointmentError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error

    def create(self, validated_data: dict[str, Any]) -> Appointment:
        return self._save(Appointment(), validated_data)

    def update(self, instance: Appointment, validated_data: dict[str, Any]) -> Appointment:
        validated_data.setdefault("end", instance.end)
        return self._save(instance, validated_data)


class AppointmentViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]
    """Записи. Фильтры: ?from=&to= (даты), ?doctor=, ?status=a,b, ?client=, ?pet=.

    Если при сохранении есть предупреждения (врач занят, не в графике…) — ответ 409
    со списком warnings; сохранить всё равно — повторить запрос с ?force=1.
    """

    serializer_class = AppointmentSerializer
    queryset = Appointment.objects.all()

    def get_queryset(self) -> QuerySet[Appointment]:
        queryset = Appointment.objects.select_related(
            "client", "pet", "doctor", "purpose"
        ).prefetch_related("client__phones")
        params = self.request.query_params
        if params.get("from") and params.get("to"):
            start = services.day_bounds(date.fromisoformat(params["from"]))[0]
            end = services.day_bounds(date.fromisoformat(params["to"]))[1]
            queryset = queryset.filter(start__lt=end, end__gt=start)
        for field in ("doctor", "client", "pet"):
            if value := params.get(field):
                queryset = queryset.filter(**{field: value})
        if value := params.get("status"):
            queryset = queryset.filter(status__in=value.split(","))
        if params.get("upcoming", "").lower() in {"1", "true"}:
            queryset = queryset.filter(status__in=services.ACTIVE, end__gte=timezone.now())
        return queryset

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, services.AppointmentWarning):
            return Response({"warnings": exc.warnings}, status=status.HTTP_409_CONFLICT)
        return super().handle_exception(exc)

    @action(detail=True, methods=["post"], url_path="status")
    def set_status(self, request: Request, pk: str | None = None) -> Response:
        """Сменить статус: {"status": "waiting", "reason": "…" (для отмены)}."""
        appointment = self.get_object()
        try:
            services.change_status(
                appointment, request.data.get("status", ""), request.data.get("reason", "")
            )
        except (services.AppointmentError, ValueError) as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        return Response(self.get_serializer(appointment).data)

    @action(detail=False, methods=["post"], url_path="walk-in")
    def walk_in(self, request: Request) -> Response:
        """Клиент без записи — сразу в очередь «ожидает»."""
        data = self.get_serializer(data={**request.data, "start": timezone.now().isoformat()})
        data.is_valid(raise_exception=True)
        appointment = Appointment(
            **{k: v for k, v in data.validated_data.items() if k not in {"new_client", "end"}}
        )
        try:
            if quick := data.validated_data.get("new_client"):
                appointment.client = services.quick_client(**quick)
            if not appointment.client_id:
                raise services.AppointmentError("Выберите клиента или заведите нового.")
            services.walk_in(appointment)
        except services.AppointmentError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        return Response(self.get_serializer(appointment).data, status=201)


class CalendarView(APIView):
    """День календаря: колонки врачей с их графиком и записи. ?date=ГГГГ-ММ-ДД."""

    queryset = Appointment.objects.none()  # права — как на записи

    def get(self, request: Request) -> Response:
        try:
            day = date.fromisoformat(request.query_params.get("date", ""))
        except ValueError:
            day = timezone.localdate()
        start, end = services.day_bounds(day)
        appointments = list(
            services.between(start, end).prefetch_related("client__phones").order_by("start")
        )
        doctors = list(staff.schedule_users())
        known = {d.pk for d in doctors}
        doctors += [a.doctor for a in appointments if a.doctor and a.doctor.pk not in known]
        intervals = list(staff.intervals_between(start, end))
        context = {"request": request}
        return Response(
            {
                "date": day.isoformat(),
                "doctors": [
                    {
                        "id": str(doctor.pk),
                        "name": doctor.short_name or doctor.username,
                        "color": staff.employee_color(doctor),
                        "intervals": [
                            {
                                "start": i.start,
                                "end": i.end,
                                "type": i.interval_type.name,
                                "is_working": i.interval_type.is_working,
                                "color": i.interval_type.color,
                            }
                            for i in intervals
                            if i.user_id == doctor.pk
                        ],
                    }
                    for doctor in dict.fromkeys(doctors)
                ],  # fmt: skip
                "appointments": AppointmentSerializer(
                    appointments, many=True, context=context
                ).data,
            }
        )
