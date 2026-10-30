"""API медкарты: записи приёма, диагнозы, профилактика, печать."""

from datetime import date
from typing import Any

from django.db.models import QuerySet
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response

from clients.models import Pet
from core import services as core
from core.api.directories import DirectoryViewSet
from core.models import PrintTemplate
from medical import services
from medical.models import Diagnosis, Prevention, PreventionType, Visit, VisitDiagnosis, VisitResult
from scheduling import services as scheduling


class DiagnosisViewSet(DirectoryViewSet):
    model = Diagnosis
    extra_fields = ("code",)


class VisitResultViewSet(DirectoryViewSet):
    model = VisitResult


class PreventionTypeViewSet(DirectoryViewSet):
    model = PreventionType
    extra_fields = ("kind", "repeat_days", "item_required")


class VisitDiagnosisSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    name = serializers.CharField(source="diagnosis.name", read_only=True)

    class Meta:
        model = VisitDiagnosis
        fields = ["diagnosis", "kind", "name"]


class PreventionSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    type_name = serializers.CharField(source="type.name", read_only=True)
    type_kind = serializers.CharField(source="type.kind", read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True, default="")
    stage_label = serializers.CharField(source="get_stage_display", read_only=True)
    repeat_at = serializers.TimeField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = Prevention
        fields = [
            "id", "visit", "type", "type_name", "type_kind", "item", "item_name", "quantity",
            "date", "stage", "stage_label", "next_date", "reminder", "batch_note", "note",
            "repeat_at",
        ]  # fmt: skip
        read_only_fields = ["visit", "date", "reminder"]


class VisitSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    diagnoses = VisitDiagnosisSerializer(many=True, required=False)
    preventions = PreventionSerializer(many=True, read_only=True)
    items = serializers.SerializerMethodField()
    prevention_suggestions = serializers.SerializerMethodField()
    pet_name = serializers.CharField(source="pet.name", read_only=True)
    client_name = serializers.CharField(source="client.full_name", read_only=True)
    doctor_name = serializers.CharField(source="doctor.short_name", read_only=True)
    purpose_name = serializers.CharField(source="purpose.name", read_only=True)
    purpose_kind = serializers.CharField(source="purpose.kind", read_only=True)
    result_name = serializers.CharField(source="result.name", read_only=True, default="")
    appointment_status = serializers.CharField(
        source="appointment.status", read_only=True, default=""
    )

    class Meta:
        model = Visit
        fields = [
            "id", "pet", "pet_name", "client", "client_name", "doctor", "doctor_name", "date",
            "purpose", "purpose_name", "purpose_kind", "result", "result_name", "appointment",
            "appointment_status", "weight", "temperature", "treatment_html",
            "recommendations_html", "next_visit_date", "diagnoses", "items", "preventions",
            "prevention_suggestions",
            "created_at", "updated_at",
        ]  # fmt: skip
        read_only_fields = ["pet", "client", "appointment"]

    def get_items(self, visit: Visit) -> list[dict[str, Any]]:
        return [
            {
                "item_unit": str(i.item_unit_id),
                "name": i.item_unit.item.name,
                "unit": i.item_unit.unit.name,
                "quantity": str(i.quantity),
                "section": i.section,
            }
            for i in visit.items.select_related("item_unit__item", "item_unit__unit")
        ]

    def get_prevention_suggestions(self, visit: Visit) -> list[dict[str, Any]]:
        return services.prevention_suggestions(visit)

    def update(self, instance: Visit, validated_data: dict[str, Any]) -> Visit:
        diagnoses = validated_data.pop("diagnoses", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        pairs = [(d["diagnosis"], d["kind"]) for d in diagnoses] if diagnoses is not None else None
        try:
            return services.save_visit(instance, pairs)
        except services.MedicalError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error


class VisitPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"


class VisitViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]
    """Записи медкарты. Фильтры: ?pet=, ?client=, ?doctor=, ?search= (кличка, владелец).

    Новая запись: POST {"pet": id} или POST /from-appointment/ {"appointment": id}.
    """

    serializer_class = VisitSerializer
    pagination_class = VisitPagination
    queryset = Visit.objects.all()

    def get_queryset(self) -> QuerySet[Visit]:
        queryset = Visit.objects.select_related(
            "pet", "client", "doctor", "purpose", "result", "appointment"
        ).prefetch_related("diagnoses__diagnosis", "preventions__type", "preventions__item")
        params = self.request.query_params
        for field in ("pet", "client", "doctor"):
            if value := params.get(field):
                queryset = queryset.filter(**{field: value})
        if search := params.get("search", "").strip():
            for word in search.split():
                queryset = queryset.filter(pet__name__icontains=word) | queryset.filter(
                    client__last_name__icontains=word
                )
        return queryset.distinct()

    def _error(self, error: Exception) -> ValidationError:
        return ValidationError({"non_field_errors": [str(error)]})

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        pet = get_object_or_404(Pet, pk=request.data.get("pet"))
        try:
            visit = services.start_visit(pet, request.user)
        except services.MedicalError as error:
            raise self._error(error) from error
        return Response(self.get_serializer(visit).data, status=201)

    @action(detail=False, methods=["post"], url_path="from-appointment")
    def from_appointment(self, request: Request) -> Response:
        """Открыть медкарту по записи на приём: существующую запись или новую."""
        appointment = scheduling.get_appointment(request.data.get("appointment"))
        if appointment is None:
            raise NotFound("Запись на приём не найдена.")
        try:
            visit = services.visit_for_appointment(appointment, request.user)
        except services.MedicalError as error:
            raise self._error(error) from error
        return Response(self.get_serializer(visit).data)

    @action(detail=False, methods=["get"])
    def doctors(self, request: Request) -> Response:
        """Кого можно выбрать врачом: работающие сотрудники, сначала те, кто в графике."""
        return Response(
            [{"id": str(u.pk), "name": u.short_name or u.username} for u in services.doctors()]
        )

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        services.delete_visit(self.get_object())
        return Response(status=204)

    @action(detail=True, methods=["post"])
    def complete(self, request: Request, pk: str | None = None) -> Response:
        """Приём окончен: запись на приём — «завершён»."""
        visit = self.get_object()
        services.complete_visit(visit)
        return Response(self.get_serializer(visit).data)

    @action(detail=True, methods=["post"])
    def prevent(self, request: Request, pk: str | None = None) -> Response:
        """Записать профилактику. repeat_at — запланировать визит на дату повтора."""
        visit = self.get_object()
        data = PreventionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        try:
            services.add_prevention(
                visit, values["type"], values.get("item"), values.get("quantity", 1),
                values.get("stage", ""), values.get("next_date"), values.get("batch_note", ""),
                values.get("note", ""), values.get("repeat_at"),
            )  # fmt: skip
        except services.MedicalError as error:
            raise self._error(error) from error
        return Response(self.get_serializer(self.get_object()).data, status=201)

    @action(
        detail=True, methods=["patch", "delete"], url_path=r"preventions/(?P<prevention_id>[^/.]+)"
    )
    def change_prevention(
        self, request: Request, pk: str | None = None, prevention_id: str | None = None
    ) -> Response:
        """Исправить (PATCH) или удалить (DELETE) процедуру — только из записи, где она создана."""
        visit = self.get_object()
        prevention = get_object_or_404(Prevention, pk=prevention_id, visit=visit)
        if request.method == "DELETE":
            prevention.delete()
        else:
            data = PreventionSerializer(prevention, data=request.data, partial=True)
            data.is_valid(raise_exception=True)
            changes = {
                k: v for k, v in data.validated_data.items()
                if k in {"item", "quantity", "stage", "next_date", "batch_note", "note"}
            }  # fmt: skip
            try:
                services.update_prevention(prevention, **changes)
            except services.MedicalError as error:
                raise self._error(error) from error
        return Response(self.get_serializer(self.get_object()).data)

    @action(detail=True, methods=["get"])
    def print(self, request: Request, pk: str | None = None) -> HttpResponse:
        """PDF записи по шаблону: ?template=<id> (по умолчанию — первый шаблон «Медкарта»)."""
        visit = self.get_object()
        templates = PrintTemplate.objects.filter(kind="medcard", is_active=True)
        template = (
            templates.filter(pk=request.query_params["template"]).first()
            if request.query_params.get("template")
            else templates.order_by("name").first()
        )
        if template is None:
            raise ValidationError({"template": ["Нет печатной формы «Медкарта»."]})
        pdf = core.render_print(template, services.print_context(visit))
        return HttpResponse(pdf, content_type="application/pdf")


def _date_param(request: Request, name: str, default: date) -> date:
    value = request.query_params.get(name)
    try:
        return date.fromisoformat(value) if value else default
    except ValueError:
        raise ValidationError({name: ["Дата в формате ГГГГ-ММ-ДД."]}) from None


class PreventionViewSet(viewsets.ReadOnlyModelViewSet):  # type: ignore[type-arg]
    """Профилактика. История питомца: ?pet=. Сводка: /summary/?pet=.
    Отчёт: /report/?mode=done|due|overdue&from=&to=&type=&species= (+ &export=xlsx).
    Что предлагать для вида: /preparations/?type=."""

    serializer_class = PreventionSerializer
    queryset = Prevention.objects.all()

    def get_queryset(self) -> QuerySet[Prevention]:
        queryset = Prevention.objects.select_related("type", "item")
        if self.action != "list":
            return queryset
        pet = self.request.query_params.get("pet")
        if not pet:
            raise ValidationError({"pet": ["Укажите питомца."]})
        return queryset.filter(pet=pet)

    @action(detail=False, methods=["get"])
    def summary(self, request: Request) -> Response:
        pet = get_object_or_404(Pet, pk=request.query_params.get("pet"))
        return Response(services.prevention_summary(pet))

    @action(detail=False, methods=["get"])
    def preparations(self, request: Request) -> Response:
        prevention_type = get_object_or_404(PreventionType, pk=request.query_params.get("type"))
        return Response(
            [{"id": str(i.pk), "name": i.name} for i in services.preparations(prevention_type)]
        )

    @action(detail=False, methods=["get"])
    def report(self, request: Request) -> HttpResponse:
        today = timezone.localdate()
        params = request.query_params
        try:
            rows = services.prevention_report(
                params.get("mode", "done"),
                _date_param(request, "from", today.replace(day=1)),
                _date_param(request, "to", today),
                params.get("type") or None,
                params.get("species") or None,
            )[:5000]
        except services.MedicalError as error:
            raise ValidationError({"mode": [str(error)]}) from error
        data = [
            {
                "id": str(p.pk), "pet": str(p.pet_id), "visit": str(p.visit_id),
                "pet_name": p.pet.name, "species": p.pet.species.name,
                "client": p.pet.owner.full_name, "client_id": str(p.pet.owner_id),
                "phone": next((ph.number for ph in p.pet.owner.phones.all()), ""),
                "type": p.type.name, "item": p.item.name if p.item else "",
                "date": p.date, "next_date": p.next_date, "doctor": p.visit.doctor.short_name,
            }
            for p in rows.prefetch_related("pet__owner__phones")
        ]  # fmt: skip
        if params.get("export") == "xlsx":
            return _xlsx(data)
        return Response(data)


def _xlsx(rows: list[dict[str, Any]]) -> HttpResponse:
    from io import BytesIO

    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Профилактика"
    sheet.append(["Дата", "Следующая", "Вид", "Препарат / услуга", "Питомец", "Вид животного",
                  "Владелец", "Телефон", "Врач"])  # fmt: skip
    for r in rows:
        sheet.append([r["date"], r["next_date"], r["type"], r["item"], r["pet_name"],
                      r["species"], r["client"], r["phone"], r["doctor"]])  # fmt: skip
    for column, width in zip("ABCDEFGHI", (12, 12, 26, 30, 16, 14, 32, 18, 16), strict=True):
        sheet.column_dimensions[column].width = width
    buffer = BytesIO()
    workbook.save(buffer)
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="prevention.xlsx"'
    return response
