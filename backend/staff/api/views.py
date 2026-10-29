"""API сотрудников и графика работы."""

from datetime import date, datetime
from typing import Any

from django.contrib.auth.models import Group
from django.db.models import QuerySet
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from core.api.directories import DirectoryViewSet
from core.models import User
from staff import services
from staff.models import Employee, IntervalTemplate, IntervalType, Position, WorkInterval


class PositionViewSet(DirectoryViewSet):
    model = Position


class IntervalTypeViewSet(DirectoryViewSet):
    model = IntervalType
    extra_fields = ("is_working", "color")


class IntervalTemplateViewSet(DirectoryViewSet):
    model = IntervalTemplate
    extra_fields = ("start_time", "end_time", "interval_type")


# --- Сотрудники --------------------------------------------------------------------

USER_FIELDS = ("username", "last_name", "first_name", "middle_name", "email", "is_active")


class EmployeeSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    username = serializers.CharField(source="user.username")
    last_name = serializers.CharField(source="user.last_name")
    first_name = serializers.CharField(source="user.first_name", required=False, allow_blank=True)
    middle_name = serializers.CharField(source="user.middle_name", required=False, allow_blank=True)
    email = serializers.EmailField(source="user.email", required=False, allow_blank=True)
    is_active = serializers.BooleanField(source="user.is_active", required=False)
    full_name = serializers.CharField(source="user.full_name", read_only=True)
    user_id = serializers.UUIDField(source="user.id", read_only=True)
    position_name = serializers.CharField(source="position.name", read_only=True, default="")
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    roles = serializers.PrimaryKeyRelatedField(
        source="user.groups", many=True, queryset=Group.objects.all(), required=False
    )

    class Meta:
        model = Employee
        fields = [
            "id", "user_id", "full_name", *USER_FIELDS, "password", "roles",
            "position", "position_name", "phone", "color", "in_schedule",
        ]  # fmt: skip

    def _save(self, employee: Employee, data: dict[str, Any]) -> Employee:
        user_data = data.pop("user", {})
        roles = user_data.pop("groups", None)
        password = data.pop("password", None) or None
        user = User() if employee._state.adding else employee.user
        request = self.context["request"]
        current_roles = set() if user._state.adding else set(user.groups.all())
        roles_changed = roles is not None and set(roles) != current_roles
        # Выдать роль — значит выдать права. Это может только тот, кто управляет ролями.
        if roles_changed and not request.user.has_perm("auth.change_group"):
            message = "Назначать роли может только тот, кто управляет ролями."
            raise ValidationError({"roles": [message]})
        for field, value in user_data.items():
            setattr(user, field, value)
        for field, value in data.items():
            setattr(employee, field, value)
        try:
            return services.save_employee(employee, user, password=password, roles=roles)
        except services.StaffError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error

    def create(self, validated_data: dict[str, Any]) -> Employee:
        return self._save(Employee(), validated_data)

    def update(self, instance: Employee, validated_data: dict[str, Any]) -> Employee:
        return self._save(instance, validated_data)


class EmployeeViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]
    """Сотрудники. Фильтры: ?active=true|false, ?schedule=true (показываемые в графике)."""

    serializer_class = EmployeeSerializer
    queryset = Employee.objects.all()

    def get_queryset(self) -> QuerySet[Employee]:
        queryset = Employee.objects.select_related("user", "position").prefetch_related(
            "user__groups"
        )
        params = self.request.query_params
        if (active := params.get("active")) is not None:
            queryset = queryset.filter(user__is_active=active.lower() in {"1", "true"})
        if params.get("schedule", "").lower() in {"1", "true"}:
            queryset = queryset.filter(in_schedule=True, user__is_active=True)
        return queryset

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Сотрудника не удаляют, а деактивируют: его имя остаётся в документах."""
        employee = self.get_object()
        employee.user.is_active = False
        employee.user.save(update_fields=["is_active"])
        return Response(status=204)


# --- График ------------------------------------------------------------------------


class IntervalSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    type_name = serializers.CharField(source="interval_type.name", read_only=True)
    type_color = serializers.CharField(source="interval_type.color", read_only=True)
    is_working = serializers.BooleanField(source="interval_type.is_working", read_only=True)

    class Meta:
        model = WorkInterval
        fields = [
            "id", "user", "start", "end", "interval_type", "type_name", "type_color",
            "is_working", "comment",
        ]  # fmt: skip

    def _save(self, interval: WorkInterval, data: dict[str, Any]) -> WorkInterval:
        for field, value in data.items():
            setattr(interval, field, value)
        try:
            return services.save_interval(interval)
        except services.StaffError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error

    def create(self, validated_data: dict[str, Any]) -> WorkInterval:
        return self._save(WorkInterval(), validated_data)

    def update(self, instance: WorkInterval, validated_data: dict[str, Any]) -> WorkInterval:
        return self._save(instance, validated_data)


def _date(value: Any, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValidationError({field: ["Укажите дату в формате ГГГГ-ММ-ДД."]}) from None


class IntervalViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]
    """График: ?from=ГГГГ-ММ-ДД&to=ГГГГ-ММ-ДД (обязательно), ?user=."""

    serializer_class = IntervalSerializer
    queryset = WorkInterval.objects.all()

    def get_queryset(self) -> QuerySet[WorkInterval]:
        if self.action != "list":
            return WorkInterval.objects.select_related("interval_type")
        params = self.request.query_params
        zone = timezone.get_current_timezone()
        start = datetime.combine(_date(params.get("from"), "from"), datetime.min.time(), zone)
        end = datetime.combine(_date(params.get("to"), "to"), datetime.max.time(), zone)
        queryset = services.intervals_between(start, end)
        if user := params.get("user"):
            queryset = queryset.filter(user=user)
        return queryset

    @action(detail=False, methods=["post"])
    def fill(self, request: Request) -> Response:
        """По шаблону: {"users": [...], "days": ["2026-11-02", ...], "template": id}."""
        template = IntervalTemplate.objects.filter(pk=request.data.get("template")).first()
        if template is None:
            raise ValidationError({"template": ["Выберите шаблон."]})
        users = list(User.objects.filter(pk__in=request.data.get("users") or []))
        days = [_date(day, "days") for day in request.data.get("days") or []]
        if not users or not days:
            raise ValidationError({"non_field_errors": ["Выберите сотрудников и дни."]})
        return Response(services.apply_template(users, days, template))

    @action(detail=False, methods=["post"], url_path="copy-week")
    def copy_week(self, request: Request) -> Response:
        """Скопировать неделю: {"from": понедельник, "to": понедельник}."""
        source = _date(request.data.get("from"), "from")
        target = _date(request.data.get("to"), "to")
        try:
            return Response(services.copy_week(source, target))
        except services.StaffError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error

    @action(detail=False, methods=["get"], url_path="on-shift")
    def on_shift(self, request: Request) -> Response:
        """Кто сейчас в смене — id сотрудников."""
        return Response(sorted(str(pk) for pk in services.on_shift_user_ids()))
