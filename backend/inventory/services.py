"""Склад: публичный вход модуля.

Отвечает за: склады, партии, приход, расход, перемещение, инвентаризация, остатки.

Публичные стыки (PROJECT_PLAN, раздел 7): available(), pick_batches(), write_off(), reverse().
Другие модули обращаются к модулю только через функции этого файла.
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, TypedDict

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q, QuerySet, Sum
from django.utils import timezone

from catalog import services as catalog
from catalog.models import Kind
from core import services as core
from inventory.models import (
    Batch,
    MinStock,
    StockDocument,
    StockLine,
    StockMovement,
    Warehouse,
)

D = Decimal
ZERO = D("0")
K = StockDocument.Kind


class StockError(Exception):
    """Складская операция невозможна. Текст — для пользователя."""


def _q(value: Decimal) -> str:
    """Количество для сообщений: 5 вместо 5.000, 1,5 вместо 1.500."""
    return format(value.normalize(), "f").replace(".", ",")


# --- Остатки -----------------------------------------------------------------------

DEPARTMENT = Warehouse.Kind.DEPARTMENT


def general_stock() -> QuerySet[StockMovement]:
    """Движения общих складов — без складов отделений (ADR-024).

    Выданное на отделение в общих остатках, счетах, медкарте и складских отчётах не видно:
    оно учитывается только в разделе «Отделения».
    """
    return StockMovement.objects.exclude(warehouse__kind=DEPARTMENT)


def _movements(
    item: Any = None, warehouse: Any = None, batch: Any = None
) -> QuerySet[StockMovement]:
    queryset = StockMovement.objects.all() if warehouse is not None else general_stock()
    if item is not None:
        queryset = queryset.filter(item=item)
    if warehouse is not None:
        queryset = queryset.filter(warehouse=warehouse)
    if batch is not None:
        queryset = queryset.filter(batch=batch)
    return queryset


def available(item: Any, warehouse: Any = None, batch: Any = None) -> Decimal:
    """Остаток в единицах учёта: на складе (или на всех), по партии (или по всем)."""
    total = _movements(item, warehouse, batch).aggregate(total=Sum("qty_base"))["total"]
    return total or ZERO


@dataclass
class BatchStock:
    batch: Batch
    warehouse_id: Any
    qty: Decimal


def batch_stock(item: Any, warehouse: Any = None) -> list[BatchStock]:
    """Партии товара с остатком — по порядку списания: сначала с ближайшим сроком годности,
    без срока — в конце; при равном сроке — поступившие раньше."""
    rows = (
        _movements(item, warehouse)
        .exclude(batch=None)
        .values("batch", "warehouse")
        .annotate(qty=Sum("qty_base"))
        .filter(qty__gt=0)
    )
    batches = {b.pk: b for b in Batch.objects.filter(pk__in=[r["batch"] for r in rows])}
    result = [BatchStock(batches[r["batch"]], r["warehouse"], r["qty"]) for r in rows]
    result.sort(
        key=lambda s: (s.batch.expiry_date is None, s.batch.expiry_date, s.batch.received_at)
    )
    return result


def pick_batches(
    item: Any, qty_base: Decimal, warehouse: Any, batch: Any = None
) -> list[BatchStock]:
    """Из каких партий списать количество: заданная партия или по сроку годности.

    Не хватает — StockError с понятным текстом (продажа в минус — вместе со счетами).
    """
    stock = [
        s
        for s in batch_stock(item, warehouse)
        if batch is None or s.batch.pk == getattr(batch, "pk", batch)
    ]
    picked: list[BatchStock] = []
    rest = qty_base
    for entry in stock:
        if rest <= 0:
            break
        take = min(entry.qty, rest)
        picked.append(BatchStock(entry.batch, entry.warehouse_id, take))
        rest -= take
    if rest > 0:
        have = qty_base - rest
        name = item.name if hasattr(item, "name") else item
        where = f" партии {batch}" if batch is not None else ""
        raise StockError(
            f"Не хватает «{name}»{where} на складе: нужно {_q(qty_base)}, есть {_q(have)}."
        )
    return picked


class BalanceRow(TypedDict):
    item: str
    item_name: str
    unit: str
    warehouse: str
    warehouse_name: str
    batch: str | None
    series: str
    expiry_date: Any
    qty: Decimal
    cost: Decimal


def balances(
    warehouse: Any = None, search: str = "", expiring_days: int | None = None
) -> list[BalanceRow]:
    """Остатки по товарам, складам и партиям (ненулевые). Склады отделений — не здесь."""
    queryset = general_stock()
    if warehouse:
        queryset = queryset.filter(warehouse=warehouse)
    for word in search.split():
        queryset = queryset.filter(Q(item__name__icontains=word) | Q(item__article__iexact=word))
    rows = (
        queryset.values(
            "item",
            "item__name",
            "item__base_unit__name",
            "warehouse",
            "warehouse__name",
            "batch",
            "batch__series",
            "batch__expiry_date",
            "batch__cost_per_base",
        )
        .annotate(qty=Sum("qty_base"))
        .exclude(qty=0)
        .order_by("item__name", F("batch__expiry_date").asc(nulls_last=True))
    )
    if expiring_days is not None:
        limit = timezone.localdate() + timedelta(days=expiring_days)
        rows = rows.filter(batch__expiry_date__lte=limit)
    return [
        {
            "item": str(r["item"]),
            "item_name": r["item__name"],
            "unit": r["item__base_unit__name"],
            "warehouse": str(r["warehouse"]),
            "warehouse_name": r["warehouse__name"],
            "batch": str(r["batch"]) if r["batch"] else None,
            "series": r["batch__series"] or "",
            "expiry_date": r["batch__expiry_date"],
            "qty": r["qty"],
            "cost": (r["batch__cost_per_base"] or ZERO) * r["qty"],
        }
        for r in rows
    ]


def with_qty_text(rows: list[Any], *fields: str, item_key: str = "item") -> list[Any]:
    """Добавить к строкам остатки словами: поле qty → qty_text («5,25 упак. / 5 упак. 2 таб.»)."""
    text = catalog.qty_formatter(row[item_key] for row in rows)
    for row in rows:
        for field in fields:
            value = row.get(field)
            row[f"{field}_text"] = text(row[item_key], value) if value is not None else ""
    return rows


# --- Черновик документа ------------------------------------------------------------


class LineData(TypedDict, total=False):
    qty_expected: Decimal | None
    item_unit: Any
    quantity: Decimal
    price: Decimal | None
    vat_percent: Decimal | None
    series: str
    expiry_date: Any
    manufacturer: Any
    batch: Any
    checklist_row: int | None


def _is_department(warehouse_id: Any) -> bool:
    return (
        warehouse_id is not None
        and Warehouse.all_objects.filter(pk=warehouse_id, kind=DEPARTMENT).exists()
    )


@transaction.atomic
def save_document(
    document: StockDocument, lines: list[LineData] | None = None, *, department_ok: bool = False
) -> StockDocument:
    """Сохранить черновик складского документа со строками.

    Документы складов отделений создаёт только раздел «Отделения» (department_ok=True).
    """
    if not department_ok and (
        _is_department(document.warehouse_id) or _is_department(document.target_warehouse_id)
    ):
        raise StockError(
            "Склад отделения пополняется и пересчитывается только в разделе «Склад → Отделения»."
        )
    if document.kind == K.TRANSFER:
        if document.target_warehouse_id is None:
            raise StockError("Выберите склад, на который перемещается товар.")
        if document.target_warehouse_id == document.warehouse_id:
            raise StockError("Склады отправителя и получателя должны быть разными.")
    else:
        document.target_warehouse = None
    if document.kind not in (K.RECEIPT, K.RETURN):
        document.counterparty = None
    document.save()
    if lines is None:
        return document
    document.lines.all().delete()
    rows = []
    for position, data in enumerate(lines):
        unit = catalog.get_item_unit(getattr(data.get("item_unit"), "pk", data.get("item_unit")))
        if unit is None:
            raise StockError("В строке не выбран товар.")
        if unit.item.kind != Kind.GOODS:
            raise StockError(
                f"«{unit.item}» — не товар: услуги и комбинации на складе не учитываются."
            )
        quantity = D(str(data.get("quantity") or 0))
        if document.kind == K.INVENTORY:
            if quantity < 0:
                raise StockError(f"«{unit.item}»: количество не может быть отрицательным.")
        elif quantity <= 0:
            raise StockError(f"«{unit.item}»: количество должно быть больше нуля.")
        price = data.get("price")
        if document.kind == K.RECEIPT and price is None:
            raise StockError(f"«{unit.item}»: укажите закупочную цену.")
        if price is not None and D(str(price)) < 0:
            raise StockError(f"«{unit.item}»: цена не может быть отрицательной.")
        rows.append(
            StockLine(
                document=document,
                item=unit.item,
                item_unit=unit,
                quantity=quantity,
                qty_base=quantity * unit.ratio,
                price=price,
                vat_percent=data.get("vat_percent"),
                series=(data.get("series") or "").strip(),
                expiry_date=data.get("expiry_date"),
                manufacturer_id=getattr(data.get("manufacturer"), "pk", data.get("manufacturer")),
                batch_id=getattr(data.get("batch"), "pk", data.get("batch"))
                if document.kind != K.RECEIPT
                else None,
                qty_expected=data.get("qty_expected") if document.kind == K.INVENTORY else None,
                checklist_row=data.get("checklist_row") if document.kind == K.INVENTORY else None,
                position=position,
            )
        )
    StockLine.objects.bulk_create(rows)
    return document


# --- Выполнение и откат -------------------------------------------------------------


def _post(
    document: StockDocument,
    item: Any,
    batch: Batch | None,
    warehouse: Any,
    qty: Decimal,
    cost: Decimal,
) -> StockMovement:
    return core.post_entry(
        StockMovement,
        document,
        item=item,
        batch=batch,
        warehouse_id=getattr(warehouse, "pk", warehouse),
        qty_base=qty,
        cost_per_base=cost,
        posted_at=document.date,
    )


def execute_stock_document(document: StockDocument) -> None:
    """Проводки документа (вызывается из core.services.execute_document в транзакции)."""
    lines = list(document.lines.select_related("item", "item_unit", "batch"))
    if not lines:
        raise StockError("В документе нет строк.")
    if document.kind == K.RECEIPT:
        for line in lines:
            if line.price is None:
                raise StockError(f"«{line.item}»: в приходе не указана цена.")
            batch = Batch.objects.create(
                item=line.item,
                receipt_line=line,
                series=line.series,
                expiry_date=line.expiry_date,
                manufacturer=line.manufacturer,
                cost_per_base=(line.price / line.item_unit.ratio).quantize(D("0.01")),
                vat_percent=line.vat_percent,
                received_at=document.date,
            )
            line.batch = batch
            line.save(update_fields=["batch"])
            _post(
                document,
                line.item,
                batch,
                document.warehouse_id,
                line.qty_base,
                batch.cost_per_base,
            )
            catalog.mark_stock_tracked(line.item)
            _close_negative(document, line.item, batch, line.qty_base)
        return
    if document.kind == K.INVENTORY:
        _execute_inventory(document, lines)
        return
    for line in lines:  # расход, возврат поставщику, перемещение
        for part in pick_batches(line.item, line.qty_base, document.warehouse_id, line.batch):
            cost = part.batch.cost_per_base
            _post(document, line.item, part.batch, document.warehouse_id, -part.qty, cost)
            if document.kind == K.TRANSFER:
                _post(document, line.item, part.batch, document.target_warehouse_id, part.qty, cost)


def _last_cost(item: Any) -> Decimal:
    """Закупочная цена последней партии — для излишка без партии."""
    batch = Batch.all_objects.filter(item=item).order_by("-received_at").first()
    return batch.cost_per_base if batch else ZERO


def _execute_inventory(document: StockDocument, lines: list[StockLine]) -> None:
    """Инвентаризация: разница между насчитанным и учётным остатком — приходом или списанием.

    Учётный остаток берётся на момент выполнения (а не заполнения), поэтому продажи,
    прошедшие между заполнением и выполнением, не исказят результат.

    Строка без партии (отсканировали упаковку, ввели срок) сначала ищет партии этого товара
    на складе с тем же сроком (и серией, если она известна с обеих сторон) — насчитанное
    сравнивается с ними, а не заводит партию-двойник рядом со старой (ADR-025).
    Не нашлось — новая партия по закупочной цене строки или последней партии.
    Строки с одним и тем же товаром, сроком и серией складываются.
    """
    taken: set[Any] = set()
    for group in _inventory_groups(lines):
        first = group[0]
        counted = sum((line.qty_base for line in group), ZERO)
        if first.batch is not None:
            taken.add(first.batch_id)
            diff = counted - available(first.item, document.warehouse_id, first.batch)
            if diff:
                _post(document, first.item, first.batch, document.warehouse_id, diff,
                      first.batch.cost_per_base)  # fmt: skip
            continue
        matches = [
            s
            for s in batch_stock(first.item, document.warehouse_id)
            if s.batch.pk not in taken
            and s.batch.expiry_date == first.expiry_date
            and (not first.series or not s.batch.series or s.batch.series == first.series)
        ]
        taken.update(s.batch.pk for s in matches)
        diff = counted - sum((s.qty for s in matches), ZERO)
        if diff > 0 and matches:
            batch = matches[-1].batch  # излишек — к самой свежей из совпавших партий
            _post(document, first.item, batch, document.warehouse_id, diff, batch.cost_per_base)
        elif diff > 0:
            priced = next((line for line in group if line.price), None)
            if priced is not None and priced.price is not None:
                cost = (priced.price / priced.item_unit.ratio).quantize(D("0.01"))
            else:
                cost = _last_cost(first.item)
            batch = Batch.objects.create(
                item=first.item,
                receipt_line=first,
                series=first.series,
                expiry_date=first.expiry_date,
                cost_per_base=cost,
                received_at=document.date,
            )
            first.batch = batch
            first.save(update_fields=["batch"])
            catalog.mark_stock_tracked(first.item)
            _post(document, first.item, batch, document.warehouse_id, diff, cost)
        elif diff < 0:
            short = -diff  # недостача — с партий с ближайшим сроком
            for stock in matches:
                take = min(stock.qty, short)
                _post(document, first.item, stock.batch, document.warehouse_id, -take,
                      stock.batch.cost_per_base)  # fmt: skip
                short -= take
                if short <= 0:
                    break


def _inventory_groups(lines: list[StockLine]) -> list[list[StockLine]]:
    """Строки инвентаризации по партиям: явная партия — сама по себе; без партии —
    товар + срок + серия. Сначала строки с партией, потом с серией, потом без неё:
    точное совпадение забирает партию раньше, чем приблизительное."""
    groups: dict[tuple[Any, ...], list[StockLine]] = {}
    for line in lines:
        if line.batch_id is not None:
            key: tuple[Any, ...] = (0, line.batch_id)
        else:
            series = line.series.strip()
            key = (1 if series else 2, line.item_id, line.expiry_date, series)
        groups.setdefault(key, []).append(line)
    return [groups[key] for key in sorted(groups, key=lambda k: k[0])]


def _check_incoming_still_here(document: StockDocument, message: str) -> None:
    """Пришедшее документом (+) ещё лежит на складе — иначе откат увёл бы остаток в минус."""
    incoming = core.entries_of(StockMovement, document).filter(qty_base__gt=0, reversal_of=None)
    for movement in incoming:
        if available(movement.item, movement.warehouse_id, movement.batch) < movement.qty_base:
            raise StockError(message.format(item=movement.item))


def rollback_stock_document(document: StockDocument) -> None:
    """Откат: обратные движения. Нельзя, если товар уже ушёл дальше (продан, перемещён)."""
    if document.kind == K.RECEIPT:
        for line in document.lines.select_related("item", "batch"):
            if line.batch is None:
                continue
            left = available(line.item, document.warehouse_id, line.batch)
            if left < line.qty_base:
                raise StockError(
                    f"Откатить приход нельзя: часть «{line.item}» из этой партии уже продана, "
                    f"списана или перемещена (осталось {_q(left)} из {_q(line.qty_base)})."
                )
    elif document.kind == K.TRANSFER:
        _check_incoming_still_here(
            document, "Откатить перемещение нельзя: «{item}» уже ушёл со склада-получателя."
        )
    elif document.kind == K.INVENTORY:
        _check_incoming_still_here(
            document, "Откатить инвентаризацию нельзя: излишек «{item}» уже продан или списан."
        )
    core.reverse_entries(StockMovement, document)
    if document.kind in (K.RECEIPT, K.INVENTORY):
        for line in document.lines.select_related("batch"):
            if line.batch is not None and line.batch.receipt_line_id == line.pk:
                batch = line.batch
                line.batch = None
                line.save(update_fields=["batch"])
                batch.receipt_line = None
                batch.save(update_fields=["receipt_line"])
                batch.delete()


# --- Стыки для других модулей (счета, медкарта) ------------------------------------


class WriteOffLine(TypedDict, total=False):
    item: Any
    qty_base: Decimal
    warehouse: Any
    batch: Any


@dataclass
class WrittenOff:
    item: Any
    batch: Batch
    qty: Decimal
    cost_per_base: Decimal


def write_off(
    lines: list[WriteOffLine], source: Any, allow_negative: bool | None = None
) -> list[WrittenOff]:
    """Списать товар от имени документа другого модуля (выполненного счёта).

    Возвращает, из каких партий и по какой себестоимости списано — счёт запишет
    фактическую себестоимость в строку (ADR-008).

    Продажа в минус (settings.ALLOW_NEGATIVE_STOCK): чего не хватает, списывается
    с последней партии товара — по её закупочной цене; партия уходит в минус,
    следующий приход его закроет (ADR-009).
    """
    if allow_negative is None:
        allow_negative = settings.ALLOW_NEGATIVE_STOCK
    result: list[WrittenOff] = []
    for line in lines:
        item, qty, warehouse = line["item"], line["qty_base"], line["warehouse"]
        warehouse_id = getattr(warehouse, "pk", warehouse)
        try:
            parts = pick_batches(item, qty, warehouse, line.get("batch"))
        except StockError:
            last = Batch.objects.filter(item=item).order_by("-received_at").first()
            if not allow_negative or last is None:
                raise
            parts = [] if line.get("batch") else batch_stock(item, warehouse)
            short = qty - sum((p.qty for p in parts), ZERO)
            parts.append(BatchStock(last, warehouse_id, short))
        for part in parts:
            core.post_entry(
                StockMovement,
                source,
                item=item,
                batch=part.batch,
                warehouse_id=warehouse_id,
                qty_base=-part.qty,
                cost_per_base=part.batch.cost_per_base,
            )
            result.append(WrittenOff(item, part.batch, part.qty, part.batch.cost_per_base))
    return result


def _close_negative(document: StockDocument, item: Any, batch: Batch, qty: Decimal) -> None:
    """Приход закрывает минус по товару на складе: недостающее «переносится» из новой
    партии в партии, ушедшие в минус (проводки — от прихода, откатываются вместе с ним)."""
    rest = qty
    negative = (
        StockMovement.objects.filter(item=item, warehouse=document.warehouse_id)
        .exclude(batch=None)
        .exclude(batch=batch)
        .values("batch")
        .annotate(total=Sum("qty_base"))
        .filter(total__lt=0)
    )
    for row in negative:
        if rest <= 0:
            break
        cover = min(-row["total"], rest)
        old = Batch.objects.get(pk=row["batch"])
        _post(document, item, old, document.warehouse_id, cover, old.cost_per_base)
        _post(document, item, batch, document.warehouse_id, -cover, batch.cost_per_base)
        rest -= cover


def negative_stock() -> list[dict[str, Any]]:
    """Товары в минусе (продано больше, чем оприходовано) — их ждёт приход."""
    rows = (
        general_stock()
        .values("item", "item__name", "item__base_unit__name", "warehouse__name")
        .annotate(qty=Sum("qty_base"))
        .filter(qty__lt=0)
        .order_by("item__name")
    )
    return [
        {
            "item": str(r["item"]),
            "item_name": r["item__name"],
            "unit": r["item__base_unit__name"],
            "warehouse_name": r["warehouse__name"],
            "qty": r["qty"],
        }
        for r in rows
    ]


def reverse(source: Any) -> None:
    """Вернуть на склад всё, что списал документ (откат счёта)."""
    core.reverse_entries(StockMovement, source)


def batches_for(item: Any) -> list[BatchStock]:
    """Партии товара с остатком на всех складах — для выбора серии в медкарте."""
    return batch_stock(item)


def get_batch(pk: Any) -> Batch | None:
    return Batch.objects.filter(pk=pk).first()


def sale_warehouses() -> QuerySet[Warehouse]:
    return Warehouse.objects.filter(is_active=True, kind=Warehouse.Kind.SALE)


# --- Инвентаризация: заполнение ----------------------------------------------------


@transaction.atomic
def fill_inventory(document: StockDocument, group: Any = None) -> StockDocument:
    """Заполнить инвентаризацию учётными остатками склада (по партиям).

    Насчитанное сразу равно учётному — остаётся исправить только расхождения.
    group — только товары этой группы.
    """
    if document.kind != K.INVENTORY:
        raise StockError("Заполнять остатками можно только инвентаризацию.")
    rows = (
        StockMovement.objects.filter(warehouse=document.warehouse_id)
        .exclude(batch=None)
        .values("item", "batch")
        .annotate(qty=Sum("qty_base"))
        .filter(qty__gt=0)
    )
    if group:
        rows = rows.filter(item__group=group)
    lines: list[LineData] = []
    for row in rows:
        unit = catalog.base_item_unit(row["item"])
        if unit is None:
            continue
        lines.append(
            {
                "item_unit": unit,
                "quantity": row["qty"] / unit.ratio,
                "batch": row["batch"],
                "qty_expected": row["qty"],
            }
        )
    lines.sort(key=lambda line: str(line["item_unit"].item.name))
    return save_document(document, lines)


# --- Минимальные остатки ------------------------------------------------------------


class LowStockRow(TypedDict):
    rule: str
    item: str
    item_name: str
    unit: str
    warehouse: str | None
    warehouse_name: str
    min_qty: Decimal
    qty: Decimal


def low_stock() -> list[LowStockRow]:
    """Товары с остатком ниже минимума — «нужно заказать»."""
    result: list[LowStockRow] = []
    for rule in MinStock.objects.select_related("item__base_unit", "warehouse"):
        qty = available(rule.item, rule.warehouse_id)
        if qty < rule.min_qty:
            result.append(
                {
                    "rule": str(rule.pk),
                    "item": str(rule.item_id),
                    "item_name": rule.item.name,
                    "unit": rule.item.base_unit.name,
                    "warehouse": str(rule.warehouse_id) if rule.warehouse_id else None,
                    "warehouse_name": rule.warehouse.name if rule.warehouse else "все склады",
                    "min_qty": rule.min_qty,
                    "qty": qty,
                }
            )
    result.sort(key=lambda row: row["item_name"])
    return result


def set_min_stock(item: Any, min_qty: Decimal, warehouse: Any = None) -> MinStock | None:
    """Задать минимум (0 — убрать правило)."""
    if min_qty < 0:
        raise StockError("Минимальный остаток не может быть отрицательным.")
    if _is_department(getattr(warehouse, "pk", warehouse)):
        raise StockError("Для отделения задаётся норма — в разделе «Склад → Отделения».")
    rule = MinStock.objects.filter(item=item, warehouse=warehouse).first()
    if min_qty == 0:
        if rule is not None:
            rule.delete()
        return None
    rule = rule or MinStock(
        item_id=getattr(item, "pk", item), warehouse_id=getattr(warehouse, "pk", warehouse)
    )
    rule.min_qty = min_qty
    rule.save()
    return rule


class StockSummary(TypedDict):
    expired: int
    expiring: int
    low: int
    negative: int
    replenish: int


def summary(days: int = 90) -> StockSummary:
    """Сводка для главной: партии просрочены, истекают за days дней, товары ниже минимума."""
    today = timezone.localdate()
    rows = (
        general_stock()
        .exclude(batch=None)
        .values("batch", "batch__expiry_date")
        .annotate(qty=Sum("qty_base"))
        .filter(qty__gt=0, batch__expiry_date__isnull=False)
    )
    expired = sum(1 for r in rows if r["batch__expiry_date"] < today)
    expiring = sum(
        1 for r in rows if today <= r["batch__expiry_date"] <= today + timedelta(days=days)
    )
    return {
        "expired": expired,
        "expiring": expiring,
        "low": len(low_stock()),
        "negative": len(negative_stock()),
        "replenish": len(to_replenish()),
    }


def current_cost(item: Any, warehouse: Any = None) -> Decimal | None:
    """Закупочная цена партии, которая спишется первой (для цены по наценке в счёте)."""
    stock = batch_stock(item, warehouse) or batch_stock(item)
    return stock[0].batch.cost_per_base if stock else None


def default_sale_warehouse() -> Warehouse | None:
    return sale_warehouses().order_by("created_at").first()


# --- Отчёты ------------------------------------------------------------------------


def turnover(
    date_from: Any, date_to: Any, warehouse: Any = None, search: str = ""
) -> list[dict[str, Any]]:
    """Движение товара за период (в единицах учёта): на начало, пришло, ушло, на конец."""
    from datetime import datetime, timedelta

    zone = timezone.get_current_timezone()
    start = datetime.combine(date_from, datetime.min.time(), zone)
    end = datetime.combine(date_to, datetime.min.time(), zone) + timedelta(days=1)
    # Откатанные документы (и их обратные записи) в оборот не попадают.
    movements = (
        StockMovement.objects.effective()
        .exclude(warehouse__kind=DEPARTMENT)
        .filter(posted_at__lt=end)
    )
    if warehouse:
        movements = movements.filter(warehouse=warehouse)
    for word in search.split():
        movements = movements.filter(item__name__icontains=word)
    rows = (
        movements.values("item", "item__name", "item__base_unit__name")
        .annotate(
            opening=Sum("qty_base", filter=Q(posted_at__lt=start)),
            incoming=Sum("qty_base", filter=Q(posted_at__gte=start, qty_base__gt=0)),
            outgoing=Sum("qty_base", filter=Q(posted_at__gte=start, qty_base__lt=0)),
        )
        .order_by("item__name")
    )
    result = []
    for r in rows:
        opening, incoming, outgoing = (
            r["opening"] or ZERO,
            r["incoming"] or ZERO,
            -(r["outgoing"] or ZERO),
        )
        if not (opening or incoming or outgoing):
            continue
        result.append(
            {
                "item": str(r["item"]),
                "name": r["item__name"],
                "unit": r["item__base_unit__name"],
                "opening": opening,
                "incoming": incoming,
                "outgoing": outgoing,
                "closing": opening + incoming - outgoing,
            }
        )
    return result


def expected_batch(item: Any, warehouse: Any = None) -> Batch | None:
    """Партия, по которой оценивается себестоимость продажи: та, что спишется первой;
    нет остатка — последняя приходованная."""
    stock = batch_stock(item, warehouse)
    return (
        stock[0].batch
        if stock
        else Batch.objects.filter(item=item).order_by("-received_at").first()
    )


def expected_cost(item: Any, warehouse: Any = None) -> Decimal | None:
    """Ожидаемая себестоимость единицы учёта при продаже: партия, которая спишется первой;
    нет остатка — последняя закупочная цена; товар ни разу не приходовали — None."""
    stock = batch_stock(item, warehouse)
    last = (
        stock[0].batch
        if stock
        else Batch.objects.filter(item=item).order_by("-received_at").first()
    )
    cost: Decimal | None = last.cost_per_base if last else None
    return cost


# --- Доступ к складам ---------------------------------------------------------------


def visible_warehouses(user: Any) -> QuerySet[Warehouse]:
    """Склады, которые видит сотрудник: без ограничения ролей — все; иначе — если у него
    есть одна из ролей склада. Суперпользователь видит все."""
    warehouses = Warehouse.objects.exclude(kind=DEPARTMENT)  # склады отделений — в «Отделениях»
    if getattr(user, "is_superuser", False):
        return warehouses
    roles = list(user.groups.values_list("pk", flat=True)) if user and user.is_authenticated else []
    return warehouses.filter(Q(access_roles=None) | Q(access_roles__in=roles)).distinct()


def storage_warehouses() -> QuerySet[Warehouse]:
    return Warehouse.objects.filter(is_active=True, kind=Warehouse.Kind.STORAGE)


# --- Пополнение оперативного склада -------------------------------------------------


class ReplenishRow(TypedDict):
    item: str
    item_name: str
    unit: str
    warehouse: str
    warehouse_name: str
    qty: Decimal  # на складе продажи (может быть в минусе — продали больше, чем переместили)
    min_qty: Decimal | None
    need: Decimal  # сколько переместить, чтобы выйти в ноль / до минимума
    available: Decimal  # есть на складах хранения


def to_replenish() -> list[ReplenishRow]:
    """«Нужно переместить»: на складе продажи товар в минусе или ниже минимума, а на складе
    хранения он есть (или нет — тогда «нужно переместить» превращается в «нужно заказать»)."""
    rows: list[ReplenishRow] = []
    storage = list(storage_warehouses().values_list("pk", flat=True))
    for warehouse in sale_warehouses():
        stock = {
            r["item"]: r["qty"]
            for r in StockMovement.objects.filter(warehouse=warehouse)
            .values("item")
            .annotate(qty=Sum("qty_base"))
        }
        minimums = {m.item_id: m.min_qty for m in MinStock.objects.filter(warehouse=warehouse)}
        for item_id in set(stock) | set(minimums):
            qty = stock.get(item_id, ZERO)
            min_qty = minimums.get(item_id)
            need = max((min_qty or ZERO) - qty, -qty, ZERO)
            if need <= 0:
                continue
            item = catalog.get_item(item_id)
            if item is None:
                continue
            available = StockMovement.objects.filter(
                item_id=item_id, warehouse__in=storage
            ).aggregate(t=Sum("qty_base"))["t"]
            rows.append(
                {
                    "item": str(item_id),
                    "item_name": item.name,
                    "unit": item.base_unit.name,
                    "warehouse": str(warehouse.pk),
                    "warehouse_name": warehouse.name,
                    "qty": qty,
                    "min_qty": min_qty,
                    "need": need,
                    "available": available or ZERO,
                }
            )
    rows.sort(key=lambda r: r["item_name"])
    return rows


# --- Перемещение по сканеру ---------------------------------------------------------

_GS = "\x1d"
# Префиксы, которые некоторые сканеры ставят перед кодом GS1 (идентификатор символики).
_SYMBOLOGY_PREFIXES = ("]d2", "]C1", "]Q3", "]e0")
# Сканер «как клавиатура» при русской раскладке печатает русские буквы вместо латинских:
# серийный номер «Честного знака» ломается. Возвращаем клавиши к английской раскладке.
_RU_KEYS = 'йцукенгшщзхъфывапролджэячсмитьбю.ЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮ,ёЁ"№;:?'
_EN_KEYS = "qwertyuiop[]asdfghjkl;'zxcvbnm,./QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>?`~@#$^&"
_FROM_RU_LAYOUT = str.maketrans(_RU_KEYS, _EN_KEYS)
_CYRILLIC = re.compile("[а-яА-ЯёЁ]")
# Окончания кода маркировки «Честный знак», когда сканер не передал разделители GS:
# серийный номер (21) переменной длины узнаётся по известному хвосту кода.
_MARKING_TAILS = (
    r"91.{4}92.{44}",  # лекарства и ветпрепараты: ключ проверки и криптоподпись
    r"93.{4}",  # короткий код проверки
    r"21.{13}91.{4}92.{44}",  # серия (10) без GS перед серийным номером
    r"21.{13}93.{4}",
)
# Поля фиксированной длины: GTIN, даты (производства, годности).
_FIXED = {"01": 14, "11": 6, "17": 6}
_VARIABLE = {"10", "21", "91", "92", "93"}


def _split_variable(rest: str) -> tuple[str, str]:
    """Поле переменной длины: до разделителя GS, а без него — до известного хвоста кода."""
    if _GS in rest:
        value, _, tail = rest.partition(_GS)
        return value, tail
    for tail in _MARKING_TAILS:
        match = re.fullmatch(rf"(.+?)({tail})", rest, flags=re.S)
        if match:
            return match.group(1), match.group(2)
    return rest, ""


def parse_gs1(code: str) -> dict[str, Any] | None:
    """Код GS1 DataMatrix с упаковки: GTIN (01), срок годности (17, ГГММДД), серия (10),
    серийный номер экземпляра (21, код маркировки «Честный знак»).

    Понимает вариант со скобками «(01)…(17)…(10)…», «сплошной» с разделителем GS и без
    него (сканер его не передал), а также код, набранный сканером в русской раскладке.
    Срока и серии в коде маркировки обычно нет — тогда expiry=None, batch="".
    Обычный штрихкод (EAN-13) — не GS1, возвращает None.
    """
    raw = code.strip()
    if _CYRILLIC.search(raw):
        raw = raw.translate(_FROM_RU_LAYOUT)
    for prefix in _SYMBOLOGY_PREFIXES:
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
    raw = raw.lstrip(_GS)
    parts: dict[str, str] = {}
    if raw.startswith("("):
        parts = dict(re.findall(r"\((\d{2,4})\)([^(]*)", raw))
    elif raw.startswith("01") and len(raw) >= 16 and raw[2:16].isdigit():
        rest = raw
        while rest:
            ai = rest[:2]
            if ai in _FIXED:
                size = _FIXED[ai]
                parts[ai], rest = rest[2 : 2 + size], rest[2 + size :]
            elif ai in _VARIABLE:
                parts[ai], rest = _split_variable(rest[2:])
            else:
                break
            rest = rest.lstrip(_GS)
    else:
        return None
    gtin = parts.get("01")
    if not gtin or not gtin.isdigit():
        return None
    expiry = None
    if len(parts.get("17", "")) == 6 and parts["17"].isdigit():
        yy, mm, dd = int(parts["17"][:2]), int(parts["17"][2:4]), int(parts["17"][4:6])
        try:
            # День 00 — «до конца месяца»; хранится 28-м числом, как и раньше,
            # чтобы срок совпадал с партиями, заведёнными до этого.
            expiry = date(2000 + yy, mm, dd) if dd else date(2000 + yy, mm, 28)
        except ValueError:
            expiry = None
    return {
        "gtin": gtin,
        "ean": gtin[1:] if gtin.startswith("0") else gtin,
        "batch": parts.get("10", ""),
        "expiry": expiry,
        "serial": parts.get("21", ""),
    }


class ScanResult(TypedDict):
    item_unit: str
    item: str
    item_name: str
    unit: str
    ratio: Decimal
    base_unit: str
    batches: list[dict[str, Any]]
    recommended: str | None
    scanned_batch: str | None
    scanned_series: str
    on_target: Decimal


def scan_for_transfer(code: str, source: Any, target: Any) -> ScanResult | None:
    """Что отсканировали для перемещения: товар, его партии на складе-источнике по сроку
    (ближайший — первым, его и рекомендуем) и сколько уже на складе-получателе.

    Если код — GS1 DataMatrix, серия и срок с упаковки сверяются с партиями.
    """
    gs1 = parse_gs1(code)
    unit = catalog.find_by_barcode(gs1["ean"] if gs1 else code)
    if unit is None and gs1:
        unit = catalog.find_by_barcode(gs1["gtin"])
    if unit is None:
        return None
    stock = batch_stock(unit.item, source)
    batches = [
        {
            "batch": str(s.batch.pk),
            "series": s.batch.series,
            "expiry_date": s.batch.expiry_date.isoformat() if s.batch.expiry_date else None,
            "qty_base": s.qty,
            "qty_unit": (s.qty / unit.ratio).quantize(Decimal("0.001")),
        }
        for s in stock
    ]
    scanned = None
    if gs1 and gs1["batch"]:
        scanned = next((b["batch"] for b in batches if b["series"] == gs1["batch"]), None)
    return {
        "item_unit": str(unit.pk),
        "item": str(unit.item_id),
        "item_name": unit.item.name,
        "unit": unit.unit.name,
        "ratio": unit.ratio,
        "base_unit": unit.item.base_unit.name,
        "batches": batches,
        "recommended": batches[0]["batch"] if batches else None,
        "scanned_batch": scanned,
        "scanned_series": gs1["batch"] if gs1 else "",
        "on_target": available(unit.item, target) if target is not None else ZERO,
    }


@transaction.atomic
def quick_transfer(source: Any, target: Any, lines: list[LineData]) -> StockDocument:
    """Перемещение по сканеру: документ «Перемещение» со строками — создать и сразу провести."""
    if getattr(source, "pk", source) == getattr(target, "pk", target):
        raise StockError("Склад-источник и склад-получатель совпадают.")
    if not lines:
        raise StockError("Нечего перемещать — отсканируйте товары.")
    document = save_document(
        StockDocument(
            kind=K.TRANSFER,
            warehouse_id=getattr(source, "pk", source),
            target_warehouse_id=getattr(target, "pk", target),
        ),
        lines,
    )
    return core.execute_document(document)


class WarehouseTotal(TypedDict):
    warehouse: str
    warehouse_name: str
    kind: str
    positions: int
    cost: Decimal


def warehouse_totals(visible: Any = None) -> list[WarehouseTotal]:
    """Остатки по складам: сколько позиций в наличии и на какую сумму по себестоимости."""
    result: dict[str, WarehouseTotal] = {}
    warehouses = {
        str(w.pk): w for w in (visible if visible is not None else Warehouse.objects.all())
    }
    for row in balances():
        key = str(row["warehouse"])
        if key not in warehouses or row["qty"] <= 0:
            continue
        total = result.setdefault(
            key,
            {
                "warehouse": key,
                "warehouse_name": row["warehouse_name"],
                "kind": warehouses[key].kind,
                "positions": 0,
                "cost": ZERO,
            },
        )
        total["cost"] += row["cost"]
    for key, total in result.items():
        total["positions"] = len({r["item"] for r in balances(key) if r["qty"] > 0})
        total["cost"] = total["cost"].quantize(Decimal("0.01"))
    return sorted(result.values(), key=lambda t: t["warehouse_name"])
