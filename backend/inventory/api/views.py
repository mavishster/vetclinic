"""API склада: склады, производители, документы (приход, расход, перемещение), остатки."""

from decimal import Decimal
from typing import Any

from django.db.models import Q, QuerySet
from django.http import HttpResponse
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog import services as catalog
from catalog.models import Item, Kind
from core import services as core
from core.api import reports
from core.api.directories import DirectoryViewSet
from core.api.permissions import can_view_cost, require_special
from core.excel import xlsx_response
from core.models import DocumentError, PrintTemplate
from inventory import importing, labels, services
from inventory.models import (
    Department,
    Manufacturer,
    MinStock,
    StockDocument,
    StockLine,
    StockMovement,
    Warehouse,
)


def _text(value: Any) -> str | None:
    """Деньги и количества в ответе — строкой, как во всём API (без потерь точности)."""
    return None if value is None else str(value)


class WarehouseViewSet(DirectoryViewSet):
    """Склады. Кто настраивает склады — видит все; остальные — только доступные их ролям."""

    model = Warehouse
    extra_fields = ("kind", "responsible", "access_roles")

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        if self.request.user.has_perm("inventory.change_warehouse"):
            return queryset
        return queryset.filter(pk__in=services.visible_warehouses(self.request.user).values("pk"))


class DepartmentViewSet(DirectoryViewSet):
    model = Department
    extra_fields = ("responsible",)


class ManufacturerViewSet(DirectoryViewSet):
    model = Manufacturer


class LineSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    item_name = serializers.CharField(source="item.name", read_only=True)
    unit_name = serializers.CharField(source="item_unit.unit.name", read_only=True)
    base_unit = serializers.CharField(source="item.base_unit.name", read_only=True)
    batch_label = serializers.SerializerMethodField()
    manufacturer_name = serializers.CharField(
        source="manufacturer.name", read_only=True, default=""
    )

    class Meta:
        model = StockLine
        fields = [
            "item_unit",
            "item",
            "item_name",
            "unit_name",
            "base_unit",
            "quantity",
            "qty_base",
            "qty_expected",
            "price",
            "vat_percent",
            "series",
            "expiry_date",
            "manufacturer",
            "manufacturer_name",
            "batch",
            "batch_label",
        ]
        read_only_fields = ["item", "qty_base"]
        extra_kwargs = {"batch": {"required": False}}

    def get_batch_label(self, line: StockLine) -> str:
        return str(line.batch) if line.batch else ""


class DocumentSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    lines = LineSerializer(many=True, required=False)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    target_warehouse_name = serializers.CharField(
        source="target_warehouse.name", read_only=True, default=""
    )
    counterparty_name = serializers.CharField(
        source="counterparty.name", read_only=True, default=""
    )
    department_name = serializers.CharField(source="department.name", read_only=True, default="")
    total = serializers.SerializerMethodField()

    class Meta:
        model = StockDocument
        fields = [
            "id",
            "number",
            "kind",
            "kind_label",
            "date",
            "status",
            "status_label",
            "warehouse",
            "warehouse_name",
            "target_warehouse",
            "target_warehouse_name",
            "counterparty",
            "counterparty_name",
            "supplier_number",
            "supplier_date",
            "reason",
            "department",
            "department_name",
            "comment",
            "lines",
            "total",
            "executed_at",
            "created_at",
        ]
        read_only_fields = ["number", "status", "executed_at"]

    def to_representation(self, document: StockDocument) -> dict[str, Any]:
        data = super().to_representation(document)
        if not can_view_cost(self.context.get("request")):
            data["total"] = None  # закупочные цены — только с особым правом
            for line in data.get("lines", []):
                line["price"] = None
        return data

    def get_total(self, document: StockDocument) -> str | None:
        """Сумма прихода по закупочным ценам."""
        if document.kind != StockDocument.Kind.RECEIPT:
            return None
        total = sum(
            ((line.price or 0) * line.quantity for line in document.lines.all()), Decimal("0")
        )
        return str(total.quantize(Decimal("0.01")))

    def _save(self, document: StockDocument, data: dict[str, Any]) -> StockDocument:
        lines = data.pop("lines", None)
        for field, value in data.items():
            setattr(document, field, value)
        try:
            return services.save_document(document, lines)
        except (services.StockError, DocumentError) as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error

    def create(self, validated_data: dict[str, Any]) -> StockDocument:
        return self._save(StockDocument(), validated_data)

    def update(self, instance: StockDocument, validated_data: dict[str, Any]) -> StockDocument:
        validated_data.pop("kind", None)  # вид документа не меняется
        return self._save(instance, validated_data)


class DocumentPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"


class DocumentViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]
    """Складские документы. Фильтры: ?kind=, ?status=, ?warehouse=, ?search= (номер, поставщик)."""

    serializer_class = DocumentSerializer
    pagination_class = DocumentPagination
    queryset = StockDocument.objects.all()

    def get_queryset(self) -> QuerySet[StockDocument]:
        queryset = StockDocument.objects.select_related(
            "warehouse", "target_warehouse", "counterparty"
        ).prefetch_related(
            "lines__item__base_unit",
            "lines__item_unit__unit",
            "lines__batch",
            "lines__manufacturer",
        )
        params = self.request.query_params
        # Документы складов, которые сотруднику не видны, — не показываются.
        visible = services.visible_warehouses(self.request.user).values("pk")
        queryset = queryset.filter(Q(warehouse__in=visible) | Q(target_warehouse__in=visible))
        for field in ("kind", "status"):
            if value := params.get(field):
                queryset = queryset.filter(**{field: value})
        if value := params.get("warehouse"):
            queryset = queryset.filter(Q(warehouse=value) | Q(target_warehouse=value))
        if search := params.get("search", "").strip():
            queryset = queryset.filter(
                Q(number__icontains=search)
                | Q(counterparty__name__icontains=search)
                | Q(supplier_number__icontains=search)
            )
        return queryset

    def _run(self, operation: Any) -> Response:
        document = self.get_object()
        try:
            operation(document)
        except (services.StockError, DocumentError) as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        return Response(self.get_serializer(self.get_object()).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        document = self.get_object()
        try:
            document.delete()  # выполненный удалить нельзя — сначала откат
        except DocumentError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        return Response(status=204)

    @action(detail=True, methods=["post"])
    def fill(self, request: Request, pk: str | None = None) -> Response:
        """Инвентаризация: заполнить учётными остатками склада (?group= — одна группа)."""
        return self._run(
            lambda doc: services.fill_inventory(doc, request.data.get("group") or None)
        )

    @action(detail=True, methods=["post"])
    def execute(self, request: Request, pk: str | None = None) -> Response:
        return self._run(core.execute_document)

    @action(detail=True, methods=["post"])
    def rollback(self, request: Request, pk: str | None = None) -> Response:
        require_special(request, "inventory.rollback_stockdocument")
        return self._run(core.rollback_document)


class StockViewSet(viewsets.ViewSet):
    """Остатки и поиск товаров для документов.

    /balances/?warehouse=&search=&expiring_days= — остатки по партиям;
    /batches/?item=&warehouse= — партии товара с остатком (для выбора партии);
    /lookup/?barcode= или ?search= — товары и их единицы для строки документа.
    """

    queryset = StockMovement.objects.none()  # права — как на движения товаров

    def get_queryset(self) -> QuerySet[StockMovement]:
        return StockMovement.objects.none()

    @action(detail=False, methods=["get"])
    def balances(self, request: Request) -> Response:
        params = request.query_params
        days = params.get("expiring_days")
        rows = services.balances(
            params.get("warehouse") or None, params.get("search", ""), int(days) if days else None
        )
        visible = {
            str(pk) for pk in services.visible_warehouses(request.user).values_list("pk", flat=True)
        }
        rows = [r for r in rows if str(r["warehouse"]) in visible]
        cost = sum((r["cost"] for r in rows), Decimal("0")).quantize(Decimal("0.01"))
        show_cost = can_view_cost(request)
        totals = {"qty_rows": len(rows), "cost": str(cost) if show_cost else None}
        for row in rows:
            row["qty"] = _text(row["qty"])  # type: ignore[typeddict-item]
            cost_text = _text(row["cost"].quantize(Decimal("0.01"))) if show_cost else None
            row["cost"] = cost_text  # type: ignore[typeddict-item]
        return Response({"rows": rows, "totals": totals})

    @action(detail=False, methods=["get"])
    def replenish(self, request: Request) -> Response:
        """«Нужно переместить» на склады продажи (оперативный): в минусе или ниже минимума."""
        visible = {
            str(pk) for pk in services.visible_warehouses(request.user).values_list("pk", flat=True)
        }
        rows = [r for r in services.to_replenish() if r["warehouse"] in visible]
        for row in rows:
            for key in ("qty", "need", "available"):
                row[key] = _text(row[key])  # type: ignore[literal-required]
            row["min_qty"] = _text(row["min_qty"]) if row["min_qty"] is not None else None  # type: ignore[typeddict-item]
        return Response(rows)

    @action(detail=False, methods=["get"])
    def low(self, request: Request) -> Response:
        """Товары ниже минимального остатка — «нужно заказать»."""
        rows = services.low_stock()
        for row in rows:
            row["min_qty"], row["qty"] = _text(row["min_qty"]), _text(row["qty"])  # type: ignore[typeddict-item]
        return Response(rows)

    @action(detail=False, methods=["get"])
    def negative(self, request: Request) -> Response:
        """Товары в минусе — продано больше, чем оприходовано; закроются приходом."""
        rows = services.negative_stock()
        for row in rows:
            row["qty"] = _text(row["qty"])
        return Response(rows)

    @action(detail=False, methods=["get"])
    def summary(self, request: Request) -> Response:
        """Сводка для главной: просрочено, истекает за 90 дней, ниже минимума."""
        return Response(services.summary())

    @action(detail=False, methods=["get"])
    def batches(self, request: Request) -> Response:
        item = request.query_params.get("item")
        warehouse = request.query_params.get("warehouse") or None
        show_cost = can_view_cost(request)
        return Response(
            [
                {
                    "batch": str(s.batch.pk),
                    "label": str(s.batch),
                    "series": s.batch.series,
                    "expiry_date": s.batch.expiry_date,
                    "warehouse": str(s.warehouse_id),
                    "qty": _text(s.qty),
                    "cost_per_base": _text(s.batch.cost_per_base) if show_cost else None,
                }
                for s in services.batch_stock(item, warehouse)
            ]
        )

    @action(detail=False, methods=["get"])
    def lookup(self, request: Request) -> Response:
        params = request.query_params
        if code := params.get("barcode", "").strip():
            unit = catalog.find_by_barcode(code)
            if unit is None or unit.item.kind != Kind.GOODS:
                return Response([])
            units = [unit]
        else:
            text = params.get("search", "").strip()
            if len(text) < 2:
                return Response([])
            items = catalog.search_items(
                Item.objects.filter(kind=Kind.GOODS, is_active=True), text
            )[:20]
            units = [
                u
                for item in items
                for u in item.units.select_related("item__base_unit", "unit").all()
            ]
        return Response(
            [
                {
                    "item_unit": str(u.pk),
                    "item": str(u.item_id),
                    "item_name": u.item.name,
                    "unit_name": u.unit.name,
                    "ratio": _text(u.ratio),
                    "base_unit": u.item.base_unit.name,
                    "for_purchase": u.for_purchase,
                    "stock": _text(services.available(u.item)),
                }
                for u in units
            ]
        )


class MinStockSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    item_name = serializers.CharField(source="item.name", read_only=True)
    unit = serializers.CharField(source="item.base_unit.name", read_only=True)
    warehouse_name = serializers.CharField(
        source="warehouse.name", read_only=True, default="все склады"
    )

    class Meta:
        model = MinStock
        fields = ["id", "item", "item_name", "unit", "warehouse", "warehouse_name", "min_qty"]

    def create(self, validated_data: dict[str, Any]) -> MinStock:
        try:
            rule = services.set_min_stock(
                validated_data["item"], validated_data["min_qty"], validated_data.get("warehouse")
            )
        except services.StockError as error:
            raise ValidationError({"min_qty": [str(error)]}) from error
        if rule is None:
            raise ValidationError({"min_qty": ["Укажите минимум больше нуля."]})
        return rule


class MinStockViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]
    """Минимальные остатки. POST с тем же товаром и складом — обновляет минимум."""

    serializer_class = MinStockSerializer
    queryset = MinStock.objects.select_related("item__base_unit", "warehouse")


# --- Этикетки и импорт остатков ------------------------------------------------------


class LabelsView(APIView):
    """PDF этикеток: {"lines": [{"item_unit", "copies", "batch"?}], "template"?: id}.

    Из прихода: {"document": id} — этикетки на каждую строку, копий — по количеству.
    """

    queryset = StockDocument.objects.none()  # права — как на складские документы

    def get_queryset(self) -> QuerySet[StockDocument]:
        return StockDocument.objects.none()

    def post(self, request: Request) -> HttpResponse:
        templates = PrintTemplate.objects.filter(kind="label", is_active=True)
        template_id = request.data.get("template")
        template = (
            templates.filter(pk=template_id).first()
            if template_id
            else templates.order_by("name").first()
        )
        if template is None:
            raise ValidationError({"template": ["Нет печатной формы «Этикетка»."]})
        if document_id := request.data.get("document"):
            document = StockDocument.objects.filter(pk=document_id).first()
            if document is None:
                raise ValidationError({"document": ["Документ не найден."]})
            lines = [
                {
                    "item_unit": line.item_unit_id,
                    "copies": int(line.quantity),
                    "batch": line.batch_id,
                }
                for line in document.lines.all()
            ]
        else:
            lines = request.data.get("lines") or []
        if not lines:
            raise ValidationError({"lines": ["Нет позиций для этикеток."]})
        return HttpResponse(labels.render(lines, template), content_type="application/pdf")


def _upload(request: Request) -> tuple[bytes, str]:
    upload = request.FILES.get("file")
    if upload is None:
        raise ValidationError({"file": ["Выберите файл."]})
    return upload.read(), upload.name or "stock.xlsx"


class StockImportView(APIView):
    """Импорт остатков: POST preview/ (проверка) и commit/ (черновик прихода), GET template/."""

    queryset = StockDocument.objects.none()  # нужны права на складские документы

    def get_queryset(self) -> QuerySet[StockDocument]:
        return StockDocument.objects.none()

    def get(self, request: Request, step: str) -> HttpResponse:
        if step != "template":
            raise ValidationError({"step": ["Неизвестный шаг."]})
        response = HttpResponse(
            importing.template(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="stock-template.xlsx"'
        return response

    def post(self, request: Request, step: str) -> Response:
        try:
            if step == "preview":
                return Response(importing.preview(*_upload(request)))
            if step == "commit":
                warehouse = request.data.get("warehouse")
                if not Warehouse.objects.filter(pk=warehouse).exists():
                    raise ValidationError({"warehouse": ["Выберите склад."]})
                return Response(importing.commit(*_upload(request), warehouse))
        except importing.ImportError_ as error:
            raise ValidationError({"file": [str(error)]}) from error
        raise ValidationError({"step": ["Неизвестный шаг."]})


class TurnoverReportView(APIView):
    """Движение товара: ?from=&to=&warehouse=&search= (&export=xlsx)."""

    queryset = StockMovement.objects.none()  # права — как на остатки

    def get_queryset(self) -> QuerySet[StockMovement]:
        return StockMovement.objects.none()

    def get(self, request: Request) -> HttpResponse:
        date_from, date_to = reports.period(request)
        params = request.query_params
        rows = services.turnover(
            date_from, date_to, params.get("warehouse") or None, params.get("search", "")
        )
        if reports.wants_excel(request):
            columns = [
                ("name", "Товар", 40),
                ("unit", "Ед.", 8),
                ("opening", "На начало", 12),
                ("incoming", "Пришло", 12),
                ("outgoing", "Ушло", 12),
                ("closing", "На конец", 12),
            ]
            return xlsx_response("turnover.xlsx", "Движение товара", columns, rows)
        return Response(reports.as_text(rows))


class TransferView(APIView):
    """Перемещение по сканеру (основной → оперативный).

    GET ?code=&from=&to= — что отсканировали: товар, партии на источнике по сроку,
    рекомендованная (ближайший срок), сколько уже на получателе.
    POST {"from", "to", "lines": [{"item_unit", "quantity", "batch"}]} — переместить.
    """

    queryset = StockDocument.objects.none()  # права — как на складские документы

    def get_queryset(self) -> QuerySet[StockDocument]:
        return StockDocument.objects.none()

    def _warehouse(self, request: Request, value: Any) -> Warehouse:
        warehouse = (
            services.visible_warehouses(request.user).filter(pk=value).first() if value else None
        )
        if warehouse is None:
            raise ValidationError({"warehouse": ["Склад не найден или недоступен."]})
        return warehouse

    def get(self, request: Request) -> Response:
        params = request.query_params
        source = self._warehouse(request, params.get("from"))
        # Списание на отделение — без склада-получателя.
        target = self._warehouse(request, params.get("to")) if params.get("to") else None
        found = services.scan_for_transfer(params.get("code", ""), source, target)
        if found is None:
            raise ValidationError({"code": ["Товар с таким кодом не найден в прайсе."]})
        data: dict[str, Any] = dict(found)
        data["ratio"], data["on_target"] = _text(found["ratio"]), _text(found["on_target"])
        for batch in data["batches"]:
            batch["qty_base"], batch["qty_unit"] = (
                _text(batch["qty_base"]),
                _text(batch["qty_unit"]),
            )
        return Response(data)

    def post(self, request: Request) -> Response:
        source = self._warehouse(request, request.data.get("from"))
        target = self._warehouse(request, request.data.get("to"))
        lines = [
            {
                "item_unit": line.get("item_unit"),
                "quantity": Decimal(str(line.get("quantity") or 0)),
                "batch": line.get("batch") or None,
            }
            for line in request.data.get("lines") or []
        ]
        try:
            document = services.quick_transfer(source, target, lines)  # type: ignore[arg-type]
        except (services.StockError, DocumentError) as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        return Response({"id": str(document.pk), "number": document.number}, status=201)


class DepartmentWriteOffView(TransferView):
    """Списание расходных материалов со склада на отделение (по сканеру).

    POST {"from", "department", "reason", "lines": [{"item_unit", "quantity", "batch"}]}.
    Сканирование — тот же GET, что у перемещения (без склада-получателя).
    """

    def post(self, request: Request) -> Response:
        source = self._warehouse(request, request.data.get("from"))
        department = Department.objects.filter(
            pk=request.data.get("department"), is_active=True
        ).first()
        lines = [
            {
                "item_unit": line.get("item_unit"),
                "quantity": Decimal(str(line.get("quantity") or 0)),
                "batch": line.get("batch") or None,
            }
            for line in request.data.get("lines") or []
        ]
        try:
            document = services.department_writeoff(
                source, department, lines, str(request.data.get("reason") or "")
            )  # type: ignore[arg-type]
        except (services.StockError, DocumentError) as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        return Response({"id": str(document.pk), "number": document.number}, status=201)


class DepartmentsReportView(APIView):
    """Расход по отделениям: ?from=&to=&department= (&export=xlsx).

    Суммы — только с правом «Видеть себестоимость».
    """

    queryset = StockMovement.objects.none()  # права — как на остатки

    def get_queryset(self) -> QuerySet[StockMovement]:
        return StockMovement.objects.none()

    def get(self, request: Request) -> HttpResponse:
        date_from, date_to = reports.period(request)
        rows = services.department_consumption(
            date_from, date_to, request.query_params.get("department") or None
        )
        hide = set() if can_view_cost(request) else {"cost"}
        if reports.wants_excel(request):
            columns = [
                ("department_name", "Отделение", 18),
                ("item_name", "Материал", 40),
                ("qty", "Количество", 12),
                ("unit", "Ед.", 8),
            ]
            if not hide:
                columns.append(("cost", "Сумма", 14))
            return xlsx_response("departments.xlsx", "Расход по отделениям", columns, rows)
        return Response(reports.as_text(rows, hide))  # type: ignore[arg-type]


class WarehouseTotalsView(APIView):
    """Остатки по складам: позиций в наличии и сумма по себестоимости (с правом)."""

    queryset = StockMovement.objects.none()

    def get_queryset(self) -> QuerySet[StockMovement]:
        return StockMovement.objects.none()

    def get(self, request: Request) -> Response:
        rows = services.warehouse_totals(services.visible_warehouses(request.user))
        hide = set() if can_view_cost(request) else {"cost"}
        return Response(reports.as_text(rows, hide))  # type: ignore[arg-type]
