"""API кассы: кассы, оплаты, кассовые операции, сводка и закрытие кассы."""

from decimal import Decimal
from typing import Any

from django.db.models import QuerySet
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response

from cash import services
from cash.models import CashMovement, CashOperation, CashRegister, CashShift, Payment
from clients.models import Client
from core import services as core
from core.api.directories import DirectoryViewSet
from core.api.permissions import require_special
from core.models import DocumentError


class CashRegisterViewSet(DirectoryViewSet):
    model = CashRegister
    extra_fields = ("kind", "responsible")


class PaymentSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    client_name = serializers.CharField(source="client.full_name", read_only=True)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "number",
            "date",
            "status",
            "status_label",
            "client",
            "client_name",
            "cash_register",
            "card_register",
            "cash_received",
            "change_given",
            "card_amount",
            "amount",
            "invoice_ids",
            "allocated",
        ]
        read_only_fields = fields


class PayInput(serializers.Serializer):  # type: ignore[type-arg]
    client = serializers.PrimaryKeyRelatedField(queryset=Client.objects.all())
    invoice_ids = serializers.ListField(child=serializers.UUIDField(), required=False)
    cash_register = serializers.PrimaryKeyRelatedField(
        queryset=CashRegister.objects.all(), required=False, allow_null=True
    )
    card_register = serializers.PrimaryKeyRelatedField(
        queryset=CashRegister.objects.all(), required=False, allow_null=True
    )
    cash_received = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=Decimal("0")
    )
    card_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=Decimal("0")
    )
    change_to_balance = serializers.BooleanField(required=False, default=False)


class Pagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"


class PaymentViewSet(viewsets.ReadOnlyModelViewSet):  # type: ignore[type-arg]
    """Оплаты. POST /pay/ — принять оплату (или аванс без счетов); POST /{id}/refund/ — возврат."""

    serializer_class = PaymentSerializer
    pagination_class = Pagination
    queryset = Payment.objects.all()

    def get_queryset(self) -> QuerySet[Payment]:
        queryset = Payment.objects.select_related("client")
        if client := self.request.query_params.get("client"):
            queryset = queryset.filter(client=client)
        return queryset

    @action(detail=False, methods=["post"])
    def pay(self, request: Request) -> Response:
        data = PayInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            payment = services.pay(data.validated_data)  # type: ignore[arg-type]
        except (services.CashError, DocumentError) as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        return Response(PaymentSerializer(payment).data, status=201)

    @action(detail=True, methods=["post"])
    def refund(self, request: Request, pk: str | None = None) -> Response:
        require_special(request, "cash.refund_payment")
        payment = self.get_object()
        try:
            core.rollback_document(payment)
        except (services.CashError, DocumentError) as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        return Response(PaymentSerializer(payment).data)


class OperationSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    register_name = serializers.CharField(source="register.name", read_only=True)
    target_register_name = serializers.CharField(
        source="target_register.name", read_only=True, default=""
    )
    client_name = serializers.CharField(source="client.full_name", read_only=True, default="")
    counterparty_name = serializers.CharField(
        source="counterparty.name", read_only=True, default=""
    )
    pin = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = CashOperation
        fields = [
            "id",
            "number",
            "date",
            "status",
            "kind",
            "kind_label",
            "register",
            "register_name",
            "target_register",
            "target_register_name",
            "amount",
            "counterparty",
            "counterparty_name",
            "client",
            "client_name",
            "purpose",
            "pin",
        ]
        read_only_fields = ["number", "date", "status"]

    def create(self, validated_data: dict[str, Any]) -> CashOperation:
        pin = validated_data.pop("pin", "")
        if validated_data.get("kind") == CashOperation.Kind.ADVANCE_RETURN:
            require_special(self.context["request"], "cash.return_advance")
        try:
            return services.operate(
                CashOperation(**validated_data), self.context["request"].user, pin
            )
        except (services.CashError, DocumentError) as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error


class CashOperationViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]
    """Кассовые операции: создание сразу проводит; POST /{id}/cancel/ — отменить (смена открыта)."""

    serializer_class = OperationSerializer
    pagination_class = Pagination
    queryset = CashOperation.objects.select_related(
        "register", "target_register", "client", "counterparty"
    )
    http_method_names = ["get", "post", "head", "options"]

    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        operation = self.get_object()
        try:
            core.rollback_document(operation)
        except (services.CashError, DocumentError) as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        return Response(self.get_serializer(operation).data)


class CashViewSet(viewsets.ViewSet):
    """Сводка и закрытие касс.

    GET /summary/, POST /close-shift/ {"register"}, GET /shifts/?register=.
    """

    queryset = CashMovement.objects.none()

    def get_queryset(self) -> QuerySet[CashMovement]:
        return CashMovement.objects.none()

    @action(detail=False, methods=["get"])
    def summary(self, request: Request) -> Response:
        rows = services.summary()
        for row in rows:
            for key in ("balance", "shift_income", "shift_expense"):
                row[key] = str(row[key])  # type: ignore[literal-required]
        return Response(rows)

    @action(detail=False, methods=["post"], url_path="close-shift")
    def close_shift(self, request: Request) -> Response:
        require_special(request, "cash.close_shift")
        register = CashRegister.objects.filter(pk=request.data.get("register")).first()
        if register is None:
            raise ValidationError({"register": ["Выберите кассу."]})
        try:
            shift = services.close_shift(register, request.user)
        except services.CashError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        return Response(_shift(shift))

    @action(detail=False, methods=["get"])
    def shifts(self, request: Request) -> Response:
        queryset = CashShift.objects.select_related("register", "closed_by")
        if register := request.query_params.get("register"):
            queryset = queryset.filter(register=register)
        return Response([_shift(s) for s in queryset[:100]])


def _shift(shift: CashShift) -> dict[str, Any]:
    return {
        "id": str(shift.pk),
        "register": shift.register.name,
        "opened_at": shift.opened_at,
        "closed_at": shift.closed_at,
        "closed_by": shift.closed_by.short_name if shift.closed_by else "",
        "income": str(shift.income),
        "expense": str(shift.expense),
        "closing_balance": str(shift.closing_balance),
    }
