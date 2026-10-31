"""API счетов: счёт со строками, выполнение и откат, подбор позиций, печать, отчёт."""

from datetime import date
from typing import Any

from django.db.models import F, Q, QuerySet
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from billing import services
from billing.models import Invoice, InvoiceLine
from clients import services as clients
from core import services as core
from core.models import DocumentError, PrintTemplate
from staff import services as staff


class LineSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    name = serializers.CharField(source="item.name", read_only=True)
    kind = serializers.CharField(source="item.kind", read_only=True)
    unit_name = serializers.SerializerMethodField()
    performer_name = serializers.CharField(
        source="performer.short_name", read_only=True, default=""
    )
    price_min = serializers.SerializerMethodField()
    price_max = serializers.SerializerMethodField()

    class Meta:
        model = InvoiceLine
        fields = [
            "id",
            "item",
            "item_unit",
            "parent",
            "name",
            "kind",
            "unit_name",
            "quantity",
            "list_price",
            "price",
            "manual_price",
            "price_min",
            "price_max",
            "discount",
            "amount",
            "performer",
            "performer_name",
            "cost",
        ]

    def get_unit_name(self, line: InvoiceLine) -> str:
        return line.item_unit.unit.name if line.item_unit else "компл."

    def get_price_min(self, line: InvoiceLine) -> str | None:
        value = line.item_unit.price_min if line.item_unit else None
        return None if value is None else str(value)

    def get_price_max(self, line: InvoiceLine) -> str | None:
        value = line.item_unit.price_max if line.item_unit else None
        return None if value is None else str(value)


class InvoiceSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    unpaid = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    payment_status = serializers.CharField(read_only=True)
    client_credit = serializers.SerializerMethodField()
    lines = LineSerializer(many=True, read_only=True)
    input_lines = serializers.ListField(
        child=serializers.DictField(), write_only=True, required=False
    )
    client_name = serializers.CharField(source="client.full_name", read_only=True)
    pet_name = serializers.CharField(source="pet.name", read_only=True, default="")
    doctor_name = serializers.CharField(source="doctor.short_name", read_only=True, default="")
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    client_balance = serializers.SerializerMethodField()
    client_discount = serializers.DecimalField(
        source="client.discount_percent", read_only=True, max_digits=5, decimal_places=2
    )

    class Meta:
        model = Invoice
        fields = [
            "id",
            "number",
            "date",
            "status",
            "status_label",
            "client",
            "client_name",
            "client_balance",
            "client_discount",
            "pet",
            "pet_name",
            "doctor",
            "doctor_name",
            "appointment",
            "visit",
            "warehouse",
            "discount_percent",
            "discount_amount",
            "subtotal",
            "discount_total",
            "total",
            "paid_amount",
            "unpaid",
            "payment_status",
            "client_credit",
            "comment",
            "lines",
            "input_lines",
            "executed_at",
            "created_at",
        ]
        read_only_fields = [
            "number",
            "status",
            "subtotal",
            "discount_total",
            "total",
            "paid_amount",
            "executed_at",
        ]

    def get_client_credit(self, invoice: Invoice) -> str:
        """Нераспределённые деньги клиента (аванс) — пойдут в оплату."""
        return str(services.client_credit(invoice.client_id))

    def get_client_balance(self, invoice: Invoice) -> str:
        return str(clients.balance(invoice.client_id))

    def _save(self, invoice: Invoice, data: dict[str, Any]) -> Invoice:
        lines = data.pop("input_lines", None)
        for field, value in data.items():
            setattr(invoice, field, value)
        try:
            return services.save_invoice(invoice, lines)  # type: ignore[arg-type]
        except (services.InvoiceError, DocumentError) as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error

    def create(self, validated_data: dict[str, Any]) -> Invoice:
        return self._save(Invoice(), validated_data)

    def update(self, instance: Invoice, validated_data: dict[str, Any]) -> Invoice:
        return self._save(instance, validated_data)


class InvoicePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"


class InvoiceViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]
    """Счета. Фильтры: ?status=, ?client=, ?pet=, ?search= (номер, клиент), ?from=&to=."""

    serializer_class = InvoiceSerializer
    pagination_class = InvoicePagination
    queryset = Invoice.objects.all()

    def get_queryset(self) -> QuerySet[Invoice]:
        queryset = Invoice.objects.select_related("client", "pet", "doctor").prefetch_related(
            "lines__item", "lines__item_unit__unit", "lines__performer"
        )
        params = self.request.query_params
        for field in ("status", "client", "pet"):
            if value := params.get(field):
                queryset = queryset.filter(**{field: value})
        if search := params.get("search", "").strip():
            queryset = queryset.filter(
                Q(number__icontains=search) | Q(client__last_name__icontains=search)
            )
        if params.get("unpaid", "").lower() in {"1", "true"}:
            queryset = queryset.filter(status=Invoice.Status.EXECUTED, paid_amount__lt=F("total"))
        if params.get("from"):
            queryset = queryset.filter(date__date__gte=params["from"])
        if params.get("to"):
            queryset = queryset.filter(date__date__lte=params["to"])
        return queryset

    def _run(self, operation: Any) -> Response:
        invoice = self.get_object()
        try:
            operation(invoice)
        except (services.InvoiceError, DocumentError) as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        return Response(self.get_serializer(self.get_object()).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        invoice = self.get_object()
        try:
            invoice.delete()  # выполненный удалить нельзя — сначала откат
        except DocumentError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        return Response(status=204)

    @action(detail=True, methods=["post"])
    def execute(self, request: Request, pk: str | None = None) -> Response:
        return self._run(core.execute_document)

    @action(detail=True, methods=["post"])
    def rollback(self, request: Request, pk: str | None = None) -> Response:
        return self._run(core.rollback_document)

    @action(detail=False, methods=["get"])
    def credit(self, request: Request) -> Response:
        """Деньги клиента: ?client= → баланс (+ аванс / − долг) и нераспределённое (аванс)."""
        client = request.query_params.get("client")
        if not client:
            raise ValidationError({"client": ["Укажите клиента."]})
        return Response(
            {"balance": str(clients.balance(client)), "credit": str(services.client_credit(client))}
        )

    @action(detail=True, methods=["patch"])
    def details(self, request: Request, pk: str | None = None) -> Response:
        """Выполненный счёт: поправить врача, питомца, исполнителей строк — без отката.
        {"doctor": id|null, "pet": id|null, "performers": {"<id строки>": id|null}}"""
        invoice = self.get_object()
        kwargs: dict[str, Any] = {}
        for field in ("doctor", "pet"):
            if field in request.data:
                kwargs[field] = request.data.get(field) or None
        try:
            services.update_details(
                invoice, performers=request.data.get("performers") or {}, **kwargs
            )
        except (services.InvoiceError, DocumentError) as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        return Response(self.get_serializer(self.get_object()).data)

    @action(detail=False, methods=["post"], url_path="from-visit")
    def from_visit(self, request: Request) -> Response:
        """Счёт по записи медкарты: черновик с отмеченными через «@» позициями."""
        from medical import services as medical

        visit = medical.get_visit(request.data.get("visit"))
        if visit is None:
            raise NotFound("Запись медкарты не найдена.")
        try:
            invoice = services.invoice_for_visit(visit)
        except services.InvoiceError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        return Response(self.get_serializer(invoice).data)

    @action(detail=False, methods=["get"])
    def lookup(self, request: Request) -> Response:
        """Позиции для счёта: ?search= или ?barcode=, ?warehouse=."""
        params = request.query_params
        return Response(
            services.lookup(
                params.get("search", ""), params.get("barcode", ""), params.get("warehouse") or None
            )
        )

    @action(detail=False, methods=["get"])
    def performers(self, request: Request) -> Response:
        """Кого можно указать исполнителем: работающие сотрудники."""
        return Response(
            [{"id": str(u.pk), "name": u.short_name or u.username} for u in staff.active_users()]
        )

    @action(detail=True, methods=["get"])
    def print(self, request: Request, pk: str | None = None) -> HttpResponse:
        invoice = self.get_object()
        templates = PrintTemplate.objects.filter(kind="invoice", is_active=True)
        template_id = request.query_params.get("template")
        template = (
            templates.filter(pk=template_id).first()
            if template_id
            else templates.order_by("name").first()
        )
        if template is None:
            raise ValidationError({"template": ["Нет печатной формы «Счёт»."]})
        return HttpResponse(
            core.render_print(template, services.print_context(invoice)),
            content_type="application/pdf",
        )


class PerformersReport(APIView):
    """Выручка по исполнителям: ?from=&to= (по умолчанию — текущий месяц)."""

    queryset = Invoice.objects.none()  # права — как на счета

    def get_queryset(self) -> QuerySet[Invoice]:
        return Invoice.objects.none()

    def get(self, request: Request) -> Response:
        today = timezone.localdate()
        try:
            date_from = date.fromisoformat(
                request.query_params.get("from") or today.replace(day=1).isoformat()
            )
            date_to = date.fromisoformat(request.query_params.get("to") or today.isoformat())
        except ValueError as error:
            raise ValidationError({"from": ["Даты в формате ГГГГ-ММ-ДД."]}) from error
        rows = services.revenue_by_performer(date_from, date_to)
        return Response([{**r, "amount": str(r["amount"]), "cost": str(r["cost"])} for r in rows])
