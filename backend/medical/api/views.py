"""API медкарты: записи приёма, диагнозы, вакцинации, печать."""

from typing import Any

from django.db.models import QuerySet
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response

from catalog import services as catalog
from clients.models import Pet
from core import services as core
from core.api.directories import DirectoryViewSet
from core.models import PrintTemplate
from medical import services
from medical.models import Diagnosis, Vaccination, Visit, VisitDiagnosis, VisitResult
from scheduling import services as scheduling


class DiagnosisViewSet(DirectoryViewSet):
    model = Diagnosis
    extra_fields = ("code",)


class VisitResultViewSet(DirectoryViewSet):
    model = VisitResult


class VisitDiagnosisSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    name = serializers.CharField(source="diagnosis.name", read_only=True)

    class Meta:
        model = VisitDiagnosis
        fields = ["diagnosis", "kind", "name"]


class VaccinationSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    vaccine_name = serializers.CharField(source="vaccine.name", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    repeat_at = serializers.TimeField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = Vaccination
        fields = [
            "id", "visit", "vaccine", "vaccine_name", "quantity", "date", "kind", "kind_label",
            "next_date", "reminder", "batch_note", "repeat_at",
        ]  # fmt: skip
        read_only_fields = ["visit", "date", "reminder"]


class VisitSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    diagnoses = VisitDiagnosisSerializer(many=True, required=False)
    vaccinations = VaccinationSerializer(many=True, read_only=True)
    items = serializers.SerializerMethodField()
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
            "recommendations_html", "next_visit_date", "diagnoses", "items", "vaccinations",
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
        ).prefetch_related("diagnoses__diagnosis", "vaccinations__vaccine")
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

    @action(detail=True, methods=["post"])
    def complete(self, request: Request, pk: str | None = None) -> Response:
        """Приём окончен: запись на приём — «завершён»."""
        visit = self.get_object()
        services.complete_visit(visit)
        return Response(self.get_serializer(visit).data)

    @action(detail=True, methods=["post"])
    def vaccinate(self, request: Request, pk: str | None = None) -> Response:
        """Добавить вакцинацию в запись. repeat_at — запланировать визит на дату повтора."""
        visit = self.get_object()
        data = VaccinationSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        try:
            services.add_vaccination(
                visit, values["vaccine"], values.get("quantity", 1),
                values.get("kind", Vaccination.Kind.PRIMARY), values.get("next_date"),
                values.get("batch_note", ""), values.get("repeat_at"),
            )  # fmt: skip
        except services.MedicalError as error:
            raise self._error(error) from error
        return Response(self.get_serializer(self.get_object()).data, status=201)

    @action(detail=True, methods=["delete"], url_path=r"vaccinations/(?P<vaccination_id>[^/.]+)")
    def remove_vaccination(
        self, request: Request, pk: str | None = None, vaccination_id: str | None = None
    ) -> Response:
        """Удалить вакцинацию — только из записи, где она создана."""
        visit = self.get_object()
        get_object_or_404(Vaccination, pk=vaccination_id, visit=visit).delete()
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


class PetVaccinationsViewSet(viewsets.ReadOnlyModelViewSet):  # type: ignore[type-arg]
    """История вакцинаций питомца: ?pet=<id>."""

    serializer_class = VaccinationSerializer
    queryset = Vaccination.objects.all()

    def get_queryset(self) -> QuerySet[Vaccination]:
        pet = self.request.query_params.get("pet")
        if not pet:
            raise ValidationError({"pet": ["Укажите питомца."]})
        return Vaccination.objects.filter(pet=pet).select_related("vaccine")


class VaccinesViewSet(viewsets.ReadOnlyModelViewSet):  # type: ignore[type-arg]
    """Вакцины для выбора в медкарте (товары групп «показывать в вакцинациях»)."""

    queryset = Vaccination.objects.none()  # права — как на вакцинации

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response([{"id": str(v.pk), "name": v.name} for v in catalog.vaccines()])
