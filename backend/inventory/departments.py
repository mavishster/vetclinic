"""Склады отделений (ADR-024): выдача, пересчёт, возврат, нормы, предупреждения, отчёты.

У каждого отделения свой склад (тип «отделение»). Он не виден в счетах, медкарте, общих
остатках и складских отчётах — только здесь.

- Выдача — перемещение с основного склада на склад отделения (единица — любая у товара).
- Внести остатки (пересчёт) — инвентаризация склада отделения: что насчитали, то и осталось;
  недостача — это расход отделения (сначала из партий с ближайшим сроком), излишек приходуется.
- Возврат — перемещение со склада отделения на основной склад.

Кто и когда: у каждого документа есть автор (created_by), кто провёл (executed_by) и дата
операции (date, по умолчанию — момент ввода).
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, TypedDict

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q, QuerySet, Sum
from django.utils import timezone

from catalog import services as catalog
from core import services as core
from inventory.models import (
    Batch,
    Department,
    DepartmentNorm,
    StockDocument,
    StockMovement,
    Warehouse,
)
from inventory.services import (
    ZERO,
    LineData,
    StockError,
    batch_stock,
    save_document,
    storage_warehouses,
)

D = Decimal
K = StockDocument.Kind
EXECUTED = StockDocument.Status.EXECUTED


# --- Склад отделения ---------------------------------------------------------------


def warehouse_of(department: Department) -> Warehouse:
    """Склад отделения; у нового отделения создаётся при первом обращении."""
    if department.warehouse_id is not None:
        assert department.warehouse is not None
        return department.warehouse
    name = f"Отделение «{department.name}»"
    warehouse = Warehouse.objects.filter(name__iexact=name).first() or Warehouse.objects.create(
        name=name, kind=Warehouse.Kind.DEPARTMENT
    )
    department.warehouse = warehouse
    department.save(update_fields=["warehouse"])
    return warehouse


def _department(value: Any) -> Department:
    department = (
        value
        if isinstance(value, Department)
        else Department.objects.filter(pk=value, is_active=True).first()
        if value
        else None
    )
    if department is None:
        raise StockError("Выберите отделение.")
    return department


def _main_warehouse(value: Any = None) -> Warehouse:
    """Склад, с которого выдают и на который возвращают: по умолчанию — основной (хранение)."""
    warehouse = (
        Warehouse.objects.exclude(kind=Warehouse.Kind.DEPARTMENT).filter(pk=value).first()
        if value
        else storage_warehouses().order_by("created_at").first()
    )
    if warehouse is None:
        raise StockError("Не найден основной склад.")
    return warehouse


def _documents(department: Department | None = None) -> QuerySet[StockDocument]:
    """Выполненные документы отделений (выдачи, пересчёты, возвраты и старые списания)."""
    queryset = StockDocument.objects.filter(status=EXECUTED, department__isnull=False)
    if department is not None:
        queryset = queryset.filter(department=department)
    return queryset


def _issues(department: Department) -> QuerySet[StockDocument]:
    return _documents(department).filter(kind=K.TRANSFER, target_warehouse=department.warehouse_id)


def _counts(department: Department) -> QuerySet[StockDocument]:
    return _documents(department).filter(kind=K.INVENTORY, warehouse=department.warehouse_id)


def _operation_date(day: date | None, department: Department, counting: bool = False) -> datetime:
    """Дата операции: по умолчанию — сейчас. Не в будущем и не раньше последнего пересчёта
    (пересчёт — не раньше последней операции отделения): иначе расход посчитается неверно."""
    now = timezone.localtime()
    if day is None or day == now.date():
        moment = now
    else:
        if day > now.date():
            raise StockError("Дата не может быть в будущем.")
        moment = datetime.combine(day, now.time(), now.tzinfo)
    last = (_documents(department) if counting else _counts(department)).order_by("-date").first()
    if last is not None and moment < last.date:
        what = "последней операции" if counting else "последнего пересчёта"
        raise StockError(
            f"Дата раньше {what} отделения ({timezone.localtime(last.date):%d.%m.%Y %H:%M}). "
            "Укажите дату не раньше неё."
        )
    return moment


def _lines(lines: list[LineData]) -> list[LineData]:
    result = [line for line in lines if D(str(line.get("quantity") or 0)) != 0]
    if not result:
        raise StockError("Добавьте материалы и количество.")
    return result


# --- Выдача, возврат, пересчёт -----------------------------------------------------


@transaction.atomic
def issue(
    department: Any,
    lines: list[LineData],
    day: date | None = None,
    source: Any = None,
    comment: str = "",
) -> StockDocument:
    """Выдать материалы на отделение: перемещение с основного склада на склад отделения.

    Количество — в любой единице товара (упак., фл., таб.); партии — по сроку годности
    (ближайший первым) или заданная.
    """
    department = _department(department)
    document = StockDocument(
        kind=K.TRANSFER,
        warehouse=_main_warehouse(source),
        target_warehouse=warehouse_of(department),
        department=department,
        date=_operation_date(day, department),
        reason=f"выдача на отделение «{department.name}»",
        comment=comment.strip(),
    )
    save_document(document, _lines(lines), department_ok=True)
    return core.execute_document(document)


@transaction.atomic
def give_back(
    department: Any,
    lines: list[LineData],
    day: date | None = None,
    target: Any = None,
    comment: str = "",
) -> StockDocument:
    """Вернуть материалы с отделения на основной склад (лишнее, истекает срок)."""
    department = _department(department)
    document = StockDocument(
        kind=K.TRANSFER,
        warehouse=warehouse_of(department),
        target_warehouse=_main_warehouse(target),
        department=department,
        date=_operation_date(day, department),
        reason=f"возврат с отделения «{department.name}»",
        comment=comment.strip(),
    )
    save_document(document, _lines(lines), department_ok=True)
    return core.execute_document(document)


class CountLine(TypedDict, total=False):
    item_unit: Any
    quantity: Decimal


@transaction.atomic
def count(
    department: Any, lines: list[CountLine], day: date | None = None, comment: str = ""
) -> StockDocument:
    """Внести остатки отделения (пересчёт): документ «Инвентаризация» склада отделения.

    lines — что насчитали; по одному товару может быть несколько строк в разных единицах
    (2 упак. + 3 таб.) — они складываются. Товары, которых нет в строках, не меняются.
    Недостача списывается как расход отделения — сначала из партий с ближайшим сроком;
    излишек добавляется к последней партии.
    """
    department = _department(department)
    warehouse = warehouse_of(department)
    moment = _operation_date(day, department, counting=True)
    counted: dict[Any, Decimal] = defaultdict(lambda: ZERO)
    items: dict[Any, Any] = {}
    for line in lines:
        unit = catalog.get_item_unit(getattr(line.get("item_unit"), "pk", line.get("item_unit")))
        if unit is None:
            raise StockError("В строке не выбран материал.")
        quantity = D(str(line.get("quantity") or 0))
        if quantity < 0:
            raise StockError(f"«{unit.item}»: остаток не может быть отрицательным.")
        counted[unit.item_id] += quantity * unit.ratio
        items[unit.item_id] = unit.item
    if not counted:
        raise StockError("Внесите остаток хотя бы по одному материалу.")
    doc_lines: list[LineData] = []
    for item_id, actual in counted.items():
        base = catalog.base_item_unit(item_id)
        if base is None:
            continue
        stock = batch_stock(item_id, warehouse)
        expected = sum((s.qty for s in stock), ZERO)
        new_qty = {s.batch.pk: s.qty for s in stock}
        if actual < expected:  # расход — из партий с ближайшим сроком
            rest = expected - actual
            for s in stock:
                take = min(s.qty, rest)
                new_qty[s.batch.pk] -= take
                rest -= take
        elif actual > expected and stock:  # излишек — к последней партии
            new_qty[stock[-1].batch.pk] += actual - expected
        if stock:
            for s in stock:
                doc_lines.append(
                    {
                        "item_unit": base,
                        "quantity": new_qty[s.batch.pk] / base.ratio,
                        "batch": s.batch,
                        "qty_expected": s.qty,
                    }
                )
        else:  # по учёту ничего — излишек станет новой партией по последней закупочной цене
            doc_lines.append(
                {"item_unit": base, "quantity": actual / base.ratio, "qty_expected": ZERO}
            )
    document = StockDocument(
        kind=K.INVENTORY,
        warehouse=warehouse,
        department=department,
        date=moment,
        reason=f"остатки отделения «{department.name}»",
        comment=comment.strip(),
    )
    save_document(document, doc_lines, department_ok=True)
    return core.execute_document(document)


def count_sheet(department: Any) -> list["BalanceRow"]:
    """Что числится за отделением — бланк для внесения остатков (с единицами товара)."""
    department = _department(department)
    rows = _balance_rows([department])
    units: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for unit in catalog.item_units_of([r["item"] for r in rows]):
        units[str(unit.item_id)].append(
            {"item_unit": str(unit.pk), "unit": unit.unit.name, "ratio": str(unit.ratio)}
        )
    for row in rows:
        row["units"] = units.get(row["item"], [])
    return rows


# --- Нормы ---------------------------------------------------------------------------


def set_norm(department: Any, item: Any, norm_qty: Decimal) -> DepartmentNorm | None:
    """Норма материала в отделении (в единицах учёта); 0 — убрать."""
    department = _department(department)
    if norm_qty < 0:
        raise StockError("Норма не может быть отрицательной.")
    item_id = getattr(item, "pk", item)
    norm = DepartmentNorm.objects.filter(department=department, item_id=item_id).first()
    if norm_qty == 0:
        if norm is not None:
            norm.delete()
        return None
    norm = norm or DepartmentNorm(department=department, item_id=item_id)
    norm.norm_qty = norm_qty
    norm.save()
    return norm


def norms(department: Any = None) -> QuerySet[DepartmentNorm]:
    queryset = DepartmentNorm.objects.select_related("department", "item__base_unit")
    if department:
        queryset = queryset.filter(department=department)
    return queryset.order_by("department__name", "item__name")


def to_norm_lines(department: Any) -> list[dict[str, Any]]:
    """«Пополнить до нормы»: сколько выдать, чтобы остаток дошёл до нормы (в единицах учёта)."""
    department = _department(department)
    balance = {r["item"]: r["qty"] for r in _balance_rows([department])}
    result = []
    for norm in norms(department):
        need = norm.norm_qty - balance.get(str(norm.item_id), ZERO)
        if need > 0:
            result.append({"item": str(norm.item_id), "item_name": norm.item.name, "need": need})
    return result


# --- Остатки отделений -----------------------------------------------------------------


class BalanceRow(TypedDict, total=False):
    department: str
    department_name: str
    item: str
    item_name: str
    unit: str
    qty: Decimal
    cost: Decimal
    expiry_date: Any
    norm: Decimal | None
    below_norm: bool
    units: list[dict[str, Any]]


def _departments(department: Any = None) -> list[Department]:
    queryset = Department.objects.filter(is_active=True).order_by("name")
    if department:
        queryset = queryset.filter(pk=getattr(department, "pk", department))
    return [d for d in queryset]


def _balance_rows(departments: list[Department], search: str = "") -> list[BalanceRow]:
    by_warehouse = {warehouse_of(d).pk: d for d in departments}
    movements = StockMovement.objects.filter(warehouse__in=list(by_warehouse))
    for word in search.split():
        movements = movements.filter(item__name__icontains=word)
    rows = (
        movements.values("warehouse", "item", "item__name", "item__base_unit__name", "batch")
        .annotate(qty=Sum("qty_base"))
        .exclude(qty=0)
    )
    batches = {
        b.pk: b for b in Batch.all_objects.filter(pk__in={r["batch"] for r in rows if r["batch"]})
    }
    norm_of = {
        (n.department_id, n.item_id): n.norm_qty
        for n in DepartmentNorm.objects.filter(department__in=departments)
    }
    result: dict[tuple[Any, Any], BalanceRow] = {}
    for r in rows:
        department = by_warehouse[r["warehouse"]]
        batch = batches.get(r["batch"])
        row = result.setdefault(
            (department.pk, r["item"]),
            {
                "department": str(department.pk),
                "department_name": department.name,
                "item": str(r["item"]),
                "item_name": r["item__name"],
                "unit": r["item__base_unit__name"],
                "qty": ZERO,
                "cost": ZERO,
                "expiry_date": None,
            },
        )
        row["qty"] += r["qty"]
        if batch is not None:
            row["cost"] += r["qty"] * batch.cost_per_base
            if (
                r["qty"] > 0
                and batch.expiry_date
                and (row["expiry_date"] is None or batch.expiry_date < row["expiry_date"])
            ):
                row["expiry_date"] = batch.expiry_date
    # Материалы с нормой, которых в отделении нет совсем, — тоже в списке (остаток 0).
    for department_id, item_id in norm_of:
        key = (department_id, item_id)
        if key in result:
            continue
        department = next(d for d in departments if d.pk == department_id)
        item = catalog.get_item(item_id)
        if item is None:
            continue
        result[key] = {
            "department": str(department.pk),
            "department_name": department.name,
            "item": str(item_id),
            "item_name": item.name,
            "unit": item.base_unit.name,
            "qty": ZERO,
            "cost": ZERO,
            "expiry_date": None,
        }
    for (department_id, item_id), row in result.items():
        norm = norm_of.get((department_id, item_id))
        row["norm"] = norm
        row["below_norm"] = norm is not None and row["qty"] < norm
        row["cost"] = row["cost"].quantize(D("0.01"))
    return sorted(result.values(), key=lambda r: (r["department_name"], r["item_name"]))


def balances(department: Any = None, search: str = "") -> list[BalanceRow]:
    """Остатки материалов в отделениях: количество, ближайший срок, сумма, норма."""
    return _balance_rows(_departments(department), search)


def totals(rows: list[BalanceRow]) -> list[dict[str, Any]]:
    """Общее количество каждого материала во всех отделениях (из строк balances())."""
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        total = result.setdefault(
            row["item"],
            {"item": row["item"], "item_name": row["item_name"], "unit": row["unit"],
             "qty": ZERO, "cost": ZERO, "departments": 0},
        )  # fmt: skip
        total["qty"] += row["qty"]
        total["cost"] += row["cost"]
        total["departments"] += 1 if row["qty"] else 0
    return sorted(result.values(), key=lambda r: r["item_name"])


# --- Последние операции и предупреждения -------------------------------------------


def _who(user: Any) -> str:
    return str(user) if user is not None else ""


def _last(queryset: QuerySet[StockDocument]) -> dict[str, Any] | None:
    document = queryset.select_related("created_by", "executed_by").order_by("-date").first()
    if document is None:
        return None
    return {
        "id": str(document.pk),
        "number": document.number,
        "date": document.date,
        "created_by": _who(document.created_by),
        "executed_by": _who(document.executed_by),
    }


def status(department: Any) -> dict[str, Any]:
    """Последняя выдача и последний пересчёт отделения; внесены ли остатки после выдачи."""
    department = _department(department)
    warehouse_of(department)
    last_issue = _last(_issues(department))
    last_count = _last(_counts(department))
    pending = last_issue is not None and (
        last_count is None or last_count["date"] < last_issue["date"]
    )
    return {
        "department": str(department.pk),
        "department_name": department.name,
        "responsible": _who(department.responsible),
        "last_issue": last_issue,
        "last_count": last_count,
        "count_pending": pending,
    }


class Alert(TypedDict):
    department: str
    department_name: str
    kind: str  # count_overdue | count_due | issue_due | below_norm
    level: str  # negative | warning
    message: str


def _days(moment: datetime, today: date) -> int:
    return (today - timezone.localtime(moment).date()).days


def _plural(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "дня"
    return "дней"


def alerts(user: Any, today: date | None = None) -> list[Alert]:
    """Предупреждения по отделениям (настройки клиники: сроки выдачи и пересчёта).

    Главный администратор (особое право «Отделения: нормы, контроль…») видит все отделения,
    ответственный за отделение — свои.
    """
    today = today or timezone.localdate()
    clinic = core.current_clinic()
    issue_days = clinic.department_issue_days
    count_from, count_due = clinic.department_count_from_days, clinic.department_count_due_days
    departments = Department.objects.filter(is_active=True).order_by("name")
    if not user.has_perm("inventory.manage_department"):
        departments = departments.filter(responsible=user)
    result: list[Alert] = []

    def add(department: Department, kind: str, level: str, message: str) -> None:
        result.append(
            {
                "department": str(department.pk),
                "department_name": department.name,
                "kind": kind,
                "level": level,
                "message": message,
            }
        )

    for department in departments:
        info = status(department)
        last_issue = info["last_issue"]
        if info["count_pending"]:
            days = _days(last_issue["date"], today)
            issued = timezone.localtime(last_issue["date"])
            since = f"выдача {issued:%d.%m}, прошло {days} {_plural(days)}"
            if count_due and days >= count_due:
                add(department, "count_overdue", "negative", f"Остатки не внесены: {since}")
            elif count_from and days >= count_from:
                add(department, "count_due", "warning", f"Пора внести остатки: {since}")
        if issue_days and last_issue is not None:
            days = _days(last_issue["date"], today)
            if days >= issue_days:
                add(department, "issue_due", "warning",
                    f"Давно не было выдачи: последняя {days} {_plural(days)} назад")  # fmt: skip
        below = sum(1 for r in _balance_rows([department]) if r["below_norm"])
        if below:
            add(department, "below_norm", "warning", f"Ниже нормы: {below} — пополните до нормы")
    return result


# --- Отчёты --------------------------------------------------------------------------


def _bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    zone = timezone.get_current_timezone()
    start = datetime.combine(date_from, datetime.min.time(), zone)
    return start, datetime.combine(date_to, datetime.min.time(), zone) + timedelta(days=1)


OPERATIONS = {
    "issue": "Выдача",
    "return": "Возврат на склад",
    "consumed": "Расход по пересчёту",
    "surplus": "Излишек по пересчёту",
    "count": "Пересчёт",
    "writeoff": "Списание на отделение",
}


def _operation(document: StockDocument, qty: Decimal) -> str:
    """Что сделал документ с остатком отделения (qty — его движение по складу отделения)."""
    if document.kind == K.TRANSFER:
        return "issue" if qty > 0 else "return"
    if document.kind == K.INVENTORY:
        return "surplus" if qty > 0 else "consumed"
    return "writeoff"


def _department_movements(
    departments: list[Department], end: datetime, item: Any = None
) -> list[dict[str, Any]]:
    """Движения складов отделений и старые «списания на отделение» до конца периода —
    по документу и товару (партии сложены). Откатанное не показывается."""
    by_warehouse = {warehouse_of(d).pk: d for d in departments}
    stock_type = ContentType.objects.get_for_model(StockDocument)
    old_docs = {
        d.pk: d
        for d in StockDocument.objects.filter(
            kind=K.WRITE_OFF, status=EXECUTED, department__in=departments
        ).exclude(warehouse__kind=Warehouse.Kind.DEPARTMENT)
    }
    movements = (
        StockMovement.objects.effective()
        .filter(posted_at__lt=end)
        .filter(
            Q(warehouse__in=list(by_warehouse))
            | Q(document_type=stock_type, document_id__in=list(old_docs))
        )
    )
    if item:
        movements = movements.filter(item=item)
    grouped: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for m in movements.select_related("item__base_unit").order_by("posted_at", "created_at"):
        if m.warehouse_id in by_warehouse:
            department = by_warehouse[m.warehouse_id]
        else:  # старое списание на отделение: расход сразу, остаток отделения не меняется
            department = next(
                d for d in departments if d.pk == old_docs[m.document_id].department_id
            )
        qty = m.qty_base
        key = (m.document_id, department.pk, m.item_id)
        row = grouped.setdefault(
            key,
            {
                "document_id": m.document_id,
                "department": department,
                "item": m.item_id,
                "item_name": m.item.name,
                "unit": m.item.base_unit.name,
                "posted_at": m.posted_at,
                "qty": ZERO,
                "cost": ZERO,
                "old": m.warehouse_id not in by_warehouse,
            },
        )
        row["qty"] += qty
        row["cost"] += qty * m.cost_per_base
    return list(grouped.values())


def summary(date_from: date, date_to: date, department: Any = None) -> list[dict[str, Any]]:
    """Сводка за период по отделению и материалу: на начало, выдано, возвращено,
    израсходовано (по пересчётам и старым списаниям), излишек, на конец, сумма расхода.

    not_counted — после последней выдачи (до конца периода) остатки не вносились:
    расход по этой выдаче ещё неизвестен.
    """
    departments = _departments(department)
    start, end = _bounds(date_from, date_to)
    rows = _department_movements(departments, end)
    documents = {
        d.pk: d for d in StockDocument.objects.filter(pk__in={r["document_id"] for r in rows})
    }
    pending = {}
    for d in departments:
        last_issue = _issues(d).filter(date__lt=end).order_by("-date").first()
        last_count = _counts(d).filter(date__lt=end).order_by("-date").first()
        pending[d.pk] = last_issue is not None and (
            last_count is None or last_count.date < last_issue.date
        )
    result: dict[tuple[Any, Any], dict[str, Any]] = {}
    for r in rows:
        department = r["department"]
        row = result.setdefault(
            (department.pk, r["item"]),
            {
                "department": str(department.pk),
                "department_name": department.name,
                "item": str(r["item"]),
                "item_name": r["item_name"],
                "unit": r["unit"],
                "opening": ZERO,
                "issued": ZERO,
                "returned": ZERO,
                "consumed": ZERO,
                "surplus": ZERO,
                "closing": ZERO,
                "cost": ZERO,
                "not_counted": pending[department.pk],
            },
        )
        operation = _operation(documents[r["document_id"]], r["qty"])
        if not r["old"]:
            row["closing"] += r["qty"]
        if r["posted_at"] < start:
            if not r["old"]:
                row["opening"] += r["qty"]
            continue
        if operation == "issue":
            row["issued"] += r["qty"]
        elif operation == "return":
            row["returned"] -= r["qty"]
        elif operation == "surplus":
            row["surplus"] += r["qty"]
        else:  # consumed, writeoff
            row["consumed"] -= r["qty"]
            row["cost"] -= r["cost"]
    output = []
    for row in result.values():
        if not any(
            row[k] for k in ("opening", "issued", "returned", "consumed", "surplus", "closing")
        ):
            continue
        row["cost"] = row["cost"].quantize(D("0.01"))
        output.append(row)
    return sorted(output, key=lambda r: (r["department_name"], r["item_name"]))


def journal(
    date_from: date,
    date_to: date,
    department: Any = None,
    item: Any = None,
    user: Any = None,
) -> list[dict[str, Any]]:
    """Журнал по датам: выдачи, пересчёты (расход / излишек), возвраты, старые списания —
    с остатком отделения после операции, автором и тем, кто провёл."""
    departments = _departments(department)
    start, end = _bounds(date_from, date_to)
    rows = _department_movements(departments, end, item)
    documents = {
        d.pk: d
        for d in StockDocument.objects.filter(
            pk__in={r["document_id"] for r in rows}
        ).select_related("created_by", "executed_by")
    }
    running: dict[tuple[Any, Any], Decimal] = defaultdict(lambda: ZERO)
    result = []
    for r in sorted(rows, key=lambda r: r["posted_at"]):
        document = documents[r["document_id"]]
        key = (r["department"].pk, r["item"])
        if not r["old"]:
            running[key] += r["qty"]
        if r["posted_at"] < start:
            continue
        if (
            user
            and str(document.created_by_id) != str(user)
            and str(document.executed_by_id) != str(user)
        ):
            continue
        operation = _operation(document, r["qty"])
        result.append(
            {
                "date": r["posted_at"],
                "operation": operation,
                "operation_label": OPERATIONS[operation],
                "document": str(document.pk),
                "number": document.number,
                "department": str(r["department"].pk),
                "department_name": r["department"].name,
                "item": str(r["item"]),
                "item_name": r["item_name"],
                "unit": r["unit"],
                "qty": r["qty"],
                "balance": running[key],
                "cost": (-r["cost"] if r["qty"] < 0 else r["cost"]).quantize(D("0.01")),
                "created_by": _who(document.created_by),
                "executed_by": _who(document.executed_by),
                "comment": document.comment,
            }
        )
    result.reverse()  # новые сверху
    return result
