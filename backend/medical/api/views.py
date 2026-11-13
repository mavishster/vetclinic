"""API медкарты: записи приёма, диагнозы, профилактика, печать."""

from datetime import date
from typing import Any

from django.db.models import Q, QuerySet
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from billing import services as billing
from catalog import services as catalog
from clients.models import Pet
from core import services as core
from core.api.directories import DirectoryViewSet
from core.api.permissions import can_view_cost
from core.excel import xlsx_response
from core.models import PrintTemplate
from medical import services
from medical.models import (
    Diagnosis,
    Prescription,
    Prevention,
    PreventionType,
    TextTemplate,
    Visit,
    VisitDiagnosis,
    VisitResult,
)
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
            "date", "stage", "stage_label", "next_date", "reminder", "batch", "batch_note", "note",
            "repeat_at",
        ]  # fmt: skip
        read_only_fields = ["visit", "date", "reminder"]


class PrescriptionSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    route_label = serializers.CharField(source="get_route_display", read_only=True)
    sell_unit_name = serializers.CharField(source="sell_unit.unit.name", read_only=True, default="")

    class Meta:
        model = Prescription
        fields = [
            "item",
            "drug_name",
            "dose",
            "route",
            "route_label",
            "frequency",
            "days",
            "comment",
            "sell_unit",
            "sell_unit_name",
            "sell_qty",
        ]
        extra_kwargs = {"drug_name": {"required": False, "allow_blank": True}}


class TextTemplateSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    personal = serializers.BooleanField(write_only=True, required=False, default=False)
    is_personal = serializers.SerializerMethodField()
    purpose_name = serializers.CharField(source="purpose.name", read_only=True, default="")

    class Meta:
        model = TextTemplate
        fields = [
            "id",
            "name",
            "section",
            "purpose",
            "purpose_name",
            "body_html",
            "is_active",
            "personal",
            "is_personal",
        ]

    def get_is_personal(self, template: TextTemplate) -> bool:
        return template.owner_id is not None

    def _save(self, template: TextTemplate, data: dict[str, Any]) -> TextTemplate:
        personal = data.pop("personal", None)
        for field, value in data.items():
            setattr(template, field, value)
        if personal is not None:
            template.owner = self.context["request"].user if personal else None
        try:
            return services.save_template(template)
        except services.MedicalError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error

    def create(self, validated_data: dict[str, Any]) -> TextTemplate:
        return self._save(TextTemplate(), validated_data)

    def update(self, instance: TextTemplate, validated_data: dict[str, Any]) -> TextTemplate:
        return self._save(instance, validated_data)


class TextTemplateViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]
    """Текстовые шаблоны: общие и личные (чужие личные не видны).

    ?section=treatment|recommendations&purpose=<id> — для вкладки записи, по порядку
    (сначала для цели приёма и личные). GET /variables/ — список переменных.
    """

    serializer_class = TextTemplateSerializer
    queryset = TextTemplate.objects.all()

    def get_queryset(self) -> QuerySet[TextTemplate]:
        from django.db.models import Q

        user = self.request.user
        return TextTemplate.objects.select_related("purpose").filter(Q(owner=None) | Q(owner=user))

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        section = request.query_params.get("section")
        if section:
            found = services.templates_for(
                request.user, section, request.query_params.get("purpose")
            )
            return Response(self.get_serializer(found, many=True).data)
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=["post"], url_path="import-vetmanager",
            parser_classes=[MultiPartParser])  # fmt: skip
    def import_vetmanager(self, request: Request) -> Response:
        """Импорт общих шаблонов из VetManager (multipart: file — ответ
        MedicalCards/MedcardsTextTemplates; section; update=1 — заменить совпадающие)."""
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": ["Выберите файл."]})
        try:
            rows = services.vetmanager_templates(upload.read())
            result = services.import_vetmanager_templates(
                rows,
                request.data.get("section") or "both",
                str(request.data.get("update", "")).lower() in {"1", "true", "yes"},
            )
        except services.MedicalError as error:
            raise ValidationError({"file": [str(error)]}) from error
        return Response(result)

    @action(detail=False, methods=["get"])
    def variables(self, request: Request) -> Response:
        return Response(
            [
                {"name": f"{{{key}}}", "title": title}
                for key, (title, _) in services.TEMPLATE_VARIABLES.items()
            ]
        )


class VisitSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    diagnoses = VisitDiagnosisSerializer(many=True, required=False)
    prescriptions = PrescriptionSerializer(many=True, read_only=True)
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
    margin = serializers.SerializerMethodField()

    def get_margin(self, visit: Visit) -> dict[str, Any] | None:
        """Прибыль приёма по его счетам — только с правом «Видеть себестоимость»."""
        if visit.pk is None or not can_view_cost(self.context.get("request")):
            return None
        return billing.margin_text(billing.visit_margin(visit))

    class Meta:
        model = Visit
        fields = [
            "id", "lab_code", "pet", "pet_name", "client", "client_name", "doctor", "doctor_name",
            "date",
            "purpose", "purpose_name", "purpose_kind", "result", "result_name", "appointment",
            "appointment_status", "weight", "temperature", "treatment_html",
            "recommendations_html", "next_visit_date", "diagnoses", "items", "preventions",
            "prevention_suggestions",
            "prescriptions", "margin",
            "created_at", "updated_at",
        ]  # fmt: skip
        read_only_fields = ["lab_code", "pet", "client", "appointment"]

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
        ).prefetch_related(
            "diagnoses__diagnosis",
            "preventions__type",
            "preventions__item",
            "prescriptions__sell_unit__unit",
        )
        params = self.request.query_params
        for field in ("pet", "client", "doctor"):
            if value := params.get(field):
                queryset = queryset.filter(**{field: value})
        if search := params.get("search", "").strip():
            # Ищем и по тексту приёма: врачу нужно найти, когда он писал про «отит».
            for word in search.split():
                queryset = queryset.filter(
                    Q(pet__name__icontains=word)
                    | Q(client__last_name__icontains=word)
                    | Q(treatment_html__icontains=word)
                    | Q(recommendations_html__icontains=word)
                    | Q(diagnoses__diagnosis__name__icontains=word)
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
                values.get("note", ""), values.get("repeat_at"), values.get("batch"),
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
                if k in {"item", "quantity", "stage", "next_date", "batch", "batch_note", "note"}
            }  # fmt: skip
            try:
                services.update_prevention(prevention, **changes)
            except services.MedicalError as error:
                raise self._error(error) from error
        return Response(self.get_serializer(self.get_object()).data)

    @action(detail=True, methods=["post"], url_path="render-template")
    def render_template(self, request: Request, pk: str | None = None) -> Response:
        """Текст шаблона для вставки: переменные подставлены, поля [___] отмечены."""
        visit = self.get_object()
        template = TextTemplate.objects.filter(pk=request.data.get("template")).first()
        if template is None:
            raise ValidationError({"template": ["Шаблон не найден."]})
        return Response({"html": services.render_template(template, visit)})

    @action(detail=True, methods=["put"])
    def prescriptions(self, request: Request, pk: str | None = None) -> Response:
        """Заменить назначения записи: {"rows": [{item, drug_name, dose, route, …}]}."""
        visit = self.get_object()
        rows = PrescriptionSerializer(data=request.data.get("rows") or [], many=True)
        rows.is_valid(raise_exception=True)
        try:
            services.save_prescriptions(visit, list(rows.validated_data))
        except services.MedicalError as error:
            raise self._error(error) from error
        return Response(self.get_serializer(self.get_object()).data)

    @action(detail=True, methods=["get"], url_path="print-prescriptions")
    def print_prescriptions(self, request: Request, pk: str | None = None) -> HttpResponse:
        """Памятка владельцу: назначения и рекомендации (PDF)."""
        visit = self.get_object()
        template = (
            PrintTemplate.objects.filter(kind="prescriptions", is_active=True)
            .order_by("name")
            .first()
        )
        if template is None:
            raise ValidationError({"template": ["Нет печатной формы «Назначения»."]})
        pdf = core.render_print(template, services.prescriptions_context(visit))
        return HttpResponse(pdf, content_type="application/pdf")

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
    def batches(self, request: Request) -> Response:
        """Партии препарата с остатком: ?item=<id>."""
        return Response(
            [
                {
                    "batch": str(s.batch.pk),
                    "label": str(s.batch),
                    "qty": str(s.qty),
                    "qty_text": catalog.qty_text(s.batch.item_id, s.qty),
                }
                for s in services.batches_for(request.query_params.get("item"))
            ]
        )

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
    columns = [
        ("date", "Дата", 12),
        ("next_date", "Следующая", 12),
        ("type", "Вид", 26),
        ("item", "Препарат / услуга", 30),
        ("pet_name", "Питомец", 16),
        ("species", "Вид животного", 14),
        ("client", "Владелец", 32),
        ("phone", "Телефон", 18),
        ("doctor", "Врач", 16),
    ]
    return xlsx_response("prevention.xlsx", "Профилактика", columns, rows)
