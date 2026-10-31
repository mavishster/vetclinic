"""Склад: публичный вход модуля.

Отвечает за: склады, партии, приход, расход, перемещение, инвентаризация, остатки.

Публичные стыки (PROJECT_PLAN, раздел 7): available(), pick_batches(), write_off(), reverse().
Другие модули обращаются к модулю только через функции этого файла.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any, TypedDict

from django.db import transaction
from django.db.models import F, Q, QuerySet, Sum
from django.utils import timezone

from catalog import services as catalog
from catalog.models import Kind
from core import services as core
from inventory.models import Batch, MinStock, StockDocument, StockLine, StockMovement, Warehouse

D = Decimal
ZERO = D("0")
K = StockDocument.Kind


class StockError(Exception):
    """Складская операция невозможна. Текст — для пользователя."""


def _q(value: Decimal) -> str:
    """Количество для сообщений: 5 вместо 5.000, 1,5 вместо 1.500."""
    return format(value.normalize(), "f").replace(".", ",")


# --- Остатки -----------------------------------------------------------------------


def _movements(
    item: Any = None, warehouse: Any = None, batch: Any = None
) -> QuerySet[StockMovement]:
    queryset = StockMovement.objects.all()
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
    """Остатки по товарам, складам и партиям (ненулевые)."""
    queryset = StockMovement.objects.all()
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


@transaction.atomic
def save_document(document: StockDocument, lines: list[LineData] | None = None) -> StockDocument:
    """Сохранить черновик складского документа со строками."""
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
            assert line.price is not None
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
    Излишек товара без партии — новая партия по закупочной цене строки или последней партии.
    """
    for line in lines:
        current = available(line.item, document.warehouse_id, line.batch) if line.batch else ZERO
        diff = line.qty_base - current
        if diff == 0:
            continue
        batch = line.batch
        if batch is None:
            if diff < 0:
                continue  # нечего списывать: партии нет, учётный остаток 0
            if line.price:
                cost = (line.price / line.item_unit.ratio).quantize(D("0.01"))
            else:
                cost = _last_cost(line.item)
            batch = Batch.objects.create(
                item=line.item,
                receipt_line=line,
                series=line.series,
                expiry_date=line.expiry_date,
                cost_per_base=cost,
                received_at=document.date,
            )
            line.batch = batch
            line.save(update_fields=["batch"])
            catalog.mark_stock_tracked(line.item)
        _post(document, line.item, batch, document.warehouse_id, diff, batch.cost_per_base)


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


def write_off(lines: list[WriteOffLine], source: Any) -> list[WrittenOff]:
    """Списать товар от имени документа другого модуля (выполненного счёта).

    Возвращает, из каких партий и по какой себестоимости списано — счёт запишет
    фактическую себестоимость в строку (ADR-008).
    """
    result: list[WrittenOff] = []
    for line in lines:
        for part in pick_batches(
            line["item"], line["qty_base"], line["warehouse"], line.get("batch")
        ):
            core.post_entry(
                StockMovement,
                source,
                item=line["item"],
                batch=part.batch,
                warehouse_id=getattr(line["warehouse"], "pk", line["warehouse"]),
                qty_base=-part.qty,
                cost_per_base=part.batch.cost_per_base,
            )
            result.append(WrittenOff(line["item"], part.batch, part.qty, part.batch.cost_per_base))
    return result


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


def summary(days: int = 90) -> StockSummary:
    """Сводка для главной: партии просрочены, истекают за days дней, товары ниже минимума."""
    today = timezone.localdate()
    rows = (
        StockMovement.objects.exclude(batch=None)
        .values("batch", "batch__expiry_date")
        .annotate(qty=Sum("qty_base"))
        .filter(qty__gt=0, batch__expiry_date__isnull=False)
    )
    expired = sum(1 for r in rows if r["batch__expiry_date"] < today)
    expiring = sum(
        1 for r in rows if today <= r["batch__expiry_date"] <= today + timedelta(days=days)
    )
    return {"expired": expired, "expiring": expiring, "low": len(low_stock())}


def current_cost(item: Any, warehouse: Any = None) -> Decimal | None:
    """Закупочная цена партии, которая спишется первой (для цены по наценке в счёте)."""
    stock = batch_stock(item, warehouse) or batch_stock(item)
    return stock[0].batch.cost_per_base if stock else None


def default_sale_warehouse() -> Warehouse | None:
    return sale_warehouses().order_by("created_at").first()
