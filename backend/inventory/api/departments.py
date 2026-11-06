"""API складов отделений (ADR-024): остатки, выдача, пересчёт, возврат, нормы, отчёты.

Права:
- смотреть остатки, журнал и сводку — просмотр справочника «Отделения» или особые права
  отделений, а также ответственный за отделение;
- выдавать и возвращать — добавление складских документов;
- вносить остатки — особое право «Отделения: вносить остатки»;
- нормы — особое право «Отделения: нормы, контроль…» (главный администратор).
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from django.http import HttpResponse
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog import services as catalog
from core.api import reports
from core.api.permissions import can_view_cost, require_special
from core.excel import xlsx_response
from core.models import DocumentError
from inventory import departments as dept
from inventory.models import Department
from inventory.services import StockError, with_qty_text

VIEW_PERMS = (
    "inventory.view_department",
    "inventory.count_department",
    "inventory.manage_department",
    "inventory.add_stockdocument",
)


def _can_view(request: Request) -> bool:
    user = request.user
    return (
        any(user.has_perm(p) for p in VIEW_PERMS)
        or Department.objects.filter(responsible=user).exists()
    )


def _require_view(request: Request) -> None:
    if not _can_view(request):
        raise PermissionDenied("Нет права смотреть остатки отделений.")


def _text(rows: list[Any], request: Request, *qty_fields: str) -> list[dict[str, Any]]:
    """Остатки словами («5,25 упак. / 5 упак. 2 таб.»), числа строкой, суммы — с правом."""
    with_qty_text(rows, *qty_fields)
    hide = set() if can_view_cost(request) else {"cost"}
    return reports.as_text(rows, hide)


def _day(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as error:
        raise ValidationError({"date": ["Дата в формате ГГГГ-ММ-ДД."]}) from error


def _lines(request: Request, with_batch: bool = True) -> list[dict[str, Any]]:
    result = []
    for line in request.data.get("lines") or []:
        try:
            quantity = Decimal(str(line.get("quantity") or 0))
        except InvalidOperation as error:
            raise ValidationError({"lines": ["Количество — число."]}) from error
        row: dict[str, Any] = {"item_unit": line.get("item_unit"), "quantity": quantity}
        if with_batch:
            row["batch"] = line.get("batch") or None
        result.append(row)
    return result


def _run(operation: Any) -> Response:
    try:
        document = operation()
    except (StockError, DocumentError) as error:
        raise ValidationError({"non_field_errors": [str(error)]}) from error
    return Response({"id": str(document.pk), "number": document.number}, status=201)


class DepartmentStockView(APIView):
    """GET <step>/: list, balances, status, sheet, alerts, to-norm, norms.
    POST <step>/: issue (выдача), return (возврат), count (внести остатки), norm (норма)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, step: str) -> Response:
        params = request.query_params
        department = params.get("department") or None
        if step == "alerts":  # каждому — свои (главному администратору — все)
            return Response(dept.alerts(request.user))
        _require_view(request)
        try:
            if step == "balances":
                rows = dept.balances(department, params.get("search", ""))
                totals = dept.totals(rows)
                cost = sum((r["cost"] for r in rows), Decimal("0"))
                return Response(
                    {
                        "rows": _text(rows, request, "qty", "norm"),  # type: ignore[arg-type]
                        "totals": _text(totals, request, "qty"),
                        "cost": str(cost) if can_view_cost(request) else None,
                    }
                )
            if step == "list":  # отделения для выбора (без права на справочник)
                return Response(
                    [
                        {"id": str(d.pk), "name": d.name, "responsible": str(d.responsible or "")}
                        for d in Department.objects.filter(is_active=True).select_related(
                            "responsible"
                        )
                    ]
                )
            if step == "status":
                return Response(dept.status(department))
            if step == "sheet":
                return Response(_text(dept.count_sheet(department), request, "qty", "norm"))
            if step == "to-norm":
                lines = dept.to_norm_lines(department)
                units = catalog.item_units_of([r["item"] for r in lines])
                for line in lines:
                    line["units"] = [
                        {"item_unit": str(u.pk), "unit": u.unit.name, "ratio": str(u.ratio)}
                        for u in units
                        if str(u.item_id) == line["item"]
                    ]
                return Response(_text(lines, request, "need"))
            if step == "norms":
                rows = [
                    {
                        "id": str(n.pk),
                        "department": str(n.department_id),
                        "department_name": n.department.name,
                        "item": str(n.item_id),
                        "item_name": n.item.name,
                        "unit": n.item.base_unit.name,
                        "norm": n.norm_qty,
                    }
                    for n in dept.norms(department)
                ]
                return Response(_text(rows, request, "norm"))
        except StockError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        raise ValidationError({"step": ["Неизвестный шаг."]})

    def post(self, request: Request, step: str) -> Response:
        data = request.data
        department = data.get("department")
        day = _day(data.get("date"))
        comment = str(data.get("comment") or "")
        if step in ("issue", "return"):
            if not request.user.has_perm("inventory.add_stockdocument"):
                raise PermissionDenied("Нет права на складские документы.")
            operation = dept.issue if step == "issue" else dept.give_back
            return _run(
                lambda: operation(
                    department, _lines(request), day, data.get("warehouse") or None, comment
                )
            )
        if step == "count":
            require_special(request, "inventory.count_department")
            return _run(lambda: dept.count(department, _lines(request, False), day, comment))
        if step == "norm":
            require_special(request, "inventory.manage_department")
            item_unit = catalog.get_item_unit(data.get("item_unit"))
            if item_unit is None:
                raise ValidationError({"item_unit": ["Выберите материал."]})
            try:
                norm_qty = Decimal(str(data.get("quantity") or 0)) * item_unit.ratio
                norm = dept.set_norm(department, item_unit.item, norm_qty)
            except (StockError, InvalidOperation) as error:
                raise ValidationError({"quantity": [str(error)]}) from error
            return Response({"id": str(norm.pk) if norm else None})
        raise ValidationError({"step": ["Неизвестный шаг."]})


class DepartmentSummaryView(APIView):
    """Расход по отделениям за период: ?from=&to=&department= (&export=xlsx)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> HttpResponse:
        _require_view(request)
        date_from, date_to = reports.period(request)
        rows = dept.summary(date_from, date_to, request.query_params.get("department") or None)
        fields = ("opening", "issued", "returned", "consumed", "surplus", "closing")
        if reports.wants_excel(request):
            with_qty_text(rows, *fields)
            columns = [
                ("department_name", "Отделение", 18),
                ("item_name", "Материал", 36),
                ("opening_text", "На начало", 18),
                ("issued_text", "Выдано", 18),
                ("returned_text", "Возвращено", 18),
                ("consumed_text", "Израсходовано", 18),
                ("surplus_text", "Излишек", 14),
                ("closing_text", "На конец", 18),
            ]
            if can_view_cost(request):
                columns.append(("cost", "Сумма расхода", 14))
            return xlsx_response("departments.xlsx", "Расход по отделениям", columns, rows)
        return Response(_text(rows, request, *fields))


class DepartmentJournalView(APIView):
    """Журнал отделений по датам: ?from=&to=&department=&item=&user= (&export=xlsx)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> HttpResponse:
        _require_view(request)
        date_from, date_to = reports.period(request)
        params = request.query_params
        rows = dept.journal(
            date_from,
            date_to,
            params.get("department") or None,
            params.get("item") or None,
            params.get("user") or None,
        )
        if reports.wants_excel(request):
            with_qty_text(rows, "qty", "balance")
            for row in rows:
                row["date"] = row["date"].strftime("%d.%m.%Y %H:%M")
            columns = [
                ("date", "Дата", 16),
                ("operation_label", "Операция", 20),
                ("number", "Документ", 12),
                ("department_name", "Отделение", 16),
                ("item_name", "Материал", 32),
                ("qty_text", "Количество", 20),
                ("balance_text", "Остаток после", 20),
                ("created_by", "Ввёл", 18),
                ("executed_by", "Провёл", 18),
            ]
            return xlsx_response("department-journal.xlsx", "Журнал отделений", columns, rows)
        return Response(_text(rows, request, "qty", "balance"))
