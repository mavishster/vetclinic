"""Счета: публичный вход модуля.

Отвечает за: Счета и быстрые счета, строки, скидки и надбавки.

Другие модули обращаются к модулю только через функции этого файла.
Бизнес-правила живут здесь, а не в моделях и не в API (ENGINEERING.md).
"""

from datetime import date, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any, TypedDict

from django.db import transaction
from django.db.models import Count, F, QuerySet, Sum
from django.utils import timezone

from billing.models import Invoice, InvoiceLine, InvoiceLineBatch, InvoicePayment
from catalog import services as catalog
from catalog.models import Item, Kind
from clients import services as clients
from core import printing
from core import services as core
from core.models import Document
from inventory import services as inventory
from staff import services as staff

D = Decimal
ZERO = D("0")
CENT = D("0.01")


class InvoiceError(Exception):
    """Счёт нельзя сохранить или выполнить. Текст — для пользователя."""


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


# --- Строки ------------------------------------------------------------------------


class LineData(TypedDict, total=False):
    item_unit: Any  # товар или услуга в единице продажи
    item: Any  # комбинация
    quantity: Decimal
    price: Decimal | None  # своя цена (в границах мин./макс.)
    performer: Any
    discount_percent: Decimal | None  # скидка строки, %; ключа нет — скидка из карточки клиента
    combo_discount: Decimal | str | None  # скидка на комбинацию — позиции состава, если проходит
    goods_discount: Decimal | None  # комбинация: скидка товарам состава
    services_discount: Decimal | None  # комбинация: скидка услугам состава


def list_price(unit: Any, warehouse: Any = None) -> Decimal | None:
    """Цена по прайсу: фиксированная или по наценке от партии, которая спишется первой."""
    cost = inventory.current_cost(unit.item, warehouse) if unit.pricing == "markup" else None
    return catalog.price_of(unit, cost)


def default_performer(item: Item, invoice: Invoice) -> Any:
    """Исполнитель по умолчанию: врач счёта (из медкарты или записи на приём);
    для услуги без врача — её ответственный, который сейчас в смене, иначе первый."""
    if invoice.doctor_id:
        return invoice.doctor_id
    responsible = catalog.default_responsible(item) if item.kind == Kind.SERVICE else []
    on_shift = [user for user in responsible if staff.is_on_shift(user)]
    chosen = (on_shift or responsible or [None])[0]
    return getattr(chosen, "pk", chosen)


def _unit_line(
    invoice: Invoice, data: LineData, position: int, parent: Any = None, override: Any = None
) -> InvoiceLine:
    unit = catalog.get_item_unit(getattr(data.get("item_unit"), "pk", data.get("item_unit")))
    if unit is None:
        raise InvoiceError("В строке не выбрана позиция.")
    if unit.item.combo_only and parent is None:
        raise InvoiceError(f"«{unit.item}» продаётся только в составе комбинаций.")
    if not unit.for_sale:
        raise InvoiceError(f"«{unit.item}» не продаётся в единице «{unit.unit}».")
    quantity = D(str(data.get("quantity") or 1))
    if quantity <= 0:
        raise InvoiceError(f"«{unit.item}»: количество должно быть больше нуля.")
    base_price = override if override is not None else list_price(unit, invoice.warehouse_id)
    price = data.get("price")
    manual = price is not None and base_price is not None and D(str(price)) != base_price
    if price is None:
        price = base_price
    if price is None:
        raise InvoiceError(
            f"«{unit.item}»: цена неизвестна — нет закупочной цены для наценки. "
            "Укажите цену вручную или оформите приход."
        )
    price = D(str(price))
    if manual and not catalog.is_price_allowed(unit, price):
        low, high = unit.price_min, unit.price_max
        bounds = " ".join(
            p
            for p in (
                f"от {printing.money(low)}" if low is not None else "",
                f"до {printing.money(high)}" if high is not None else "",
            )
            if p
        )
        raise InvoiceError(
            f"«{unit.item}»: цена {printing.money(price)} вне допустимых границ ({bounds})."
        )
    if price < 0:
        raise InvoiceError(f"«{unit.item}»: цена не может быть отрицательной.")
    performer = data.get("performer") or default_performer(unit.item, invoice)
    discount = _line_discount(invoice, unit, price, manual, data)
    return InvoiceLine(
        invoice=invoice,
        item=unit.item,
        item_unit=unit,
        parent=parent,
        quantity=quantity,
        qty_base=quantity * unit.ratio,
        list_price=base_price,
        price=price,
        manual_price=manual,
        discount_percent=discount,
        performer_id=getattr(performer, "pk", performer),
        position=position,
    )


# --- Пределы скидки ----------------------------------------------------------------


def unit_cost(unit: Any, warehouse: Any = None) -> Decimal | None:
    """Себестоимость единицы продажи: товар со складом — партия, которая спишется первой;
    товар без учёта и услуга — себестоимость из карточки; неизвестна — None."""
    return unit_cost_info(unit, warehouse)[0]


def unit_cost_info(unit: Any, warehouse: Any = None) -> tuple[Decimal | None, str]:
    """Себестоимость единицы продажи и откуда она взялась — чтобы оператор мог проверить
    (например, что закупочная цена упаковки не попала в цену одной штуки)."""
    item = unit.item
    base = item.base_unit.name
    if item.kind == Kind.GOODS and item.stock_tracked:
        batch = inventory.expected_batch(item, warehouse)
        if batch is None:
            return None, ""
        cost = batch.cost_per_base
        series = f", серия {batch.series}" if batch.series else ""
        source = (
            f"партия от {batch.received_at:%d.%m.%Y}{series}: {printing.money(cost)} за 1 {base}"
        )
    else:
        cost = item.manual_cost
        if cost is None:
            return None, ""
        source = f"из карточки товара: {printing.money(cost)} за 1 {base}"
    if unit.ratio != 1 or unit.unit_id != item.base_unit_id:
        source += (
            f"; 1 {unit.unit.name} = {format(unit.ratio.normalize(), 'f').replace('.', ',')} {base}"
        )
    return _money(cost * unit.ratio), source


class DiscountLimit(TypedDict):
    percent: Decimal  # больше нельзя
    reason: str  # "limit" — лимит по типу позиции, "cost" — дальше цена ниже себестоимости
    cost: Decimal | None
    cost_source: str  # откуда себестоимость — для подсказки оператору


def discount_limit(unit: Any, price: Decimal, warehouse: Any = None) -> DiscountLimit:
    """Предельная скидка строки: лимит клиники для товаров или услуг — и не ниже себестоимости."""
    clinic = core.current_clinic()
    kind_max = (
        clinic.max_discount_goods if unit.item.kind == Kind.GOODS else clinic.max_discount_services
    )
    cost, source = unit_cost_info(unit, warehouse)
    if cost is not None:
        floor = ZERO if price <= 0 else max((price - cost) / price * 100, ZERO)
        floor = floor.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        if floor < kind_max:
            return {"percent": floor, "reason": "cost", "cost": cost, "cost_source": source}
    return {"percent": kind_max, "reason": "limit", "cost": cost, "cost_source": source}


def _combo_discount_for(item_unit: Any, data: LineData) -> Decimal | str | None:
    """Скидка позиции состава комбинации: товарам — «скидка на товары», услугам — «на услуги»
    (или общая discount_percent на всю комбинацию). Не задана — None (тогда — из карточки
    клиента); задана пустой — "" (без скидки)."""
    unit = catalog.get_item_unit(getattr(item_unit, "pk", item_unit))
    goods = unit is not None and unit.item.kind == Kind.GOODS
    for key in ("goods_discount" if goods else "services_discount", "discount_percent"):
        if key in data:
            value: Any = data.get(key)
            result: Decimal | str = "" if value in (None, "") else value
            return result
    return None


def _pct(value: Decimal) -> str:
    """5.00 → «5», 42.85 → «42,85» — проценты в сообщениях."""
    return format(value.normalize(), "f").replace(".", ",")


def _limit_error(
    item: Any, percent: Decimal, limit: DiscountLimit, what: str = "скидка"
) -> InvoiceError:
    if limit["reason"] == "cost":
        return InvoiceError(
            f"«{item}»: {what} {_pct(percent)} % опускает цену ниже себестоимости — "
            f"не больше {_pct(limit['percent'])} %."
        )
    kind = "товар" if item.kind == Kind.GOODS else "услугу"
    return InvoiceError(
        f"«{item}»: {what} {_pct(percent)} % — больше допустимой на {kind} "
        f"({_pct(limit['percent'])} %)."
    )


def _line_discount(
    invoice: Invoice, unit: Any, price: Decimal, manual: bool, data: LineData
) -> Decimal | None:
    """Скидка новой строки: указанная явно — как есть (проверяется при пересчёте);
    не указана — скидка из карточки клиента, если она в пределах для этой позиции."""
    if manual:
        return None  # своя цена — без скидки
    if "combo_discount" in data:
        value = data.get("combo_discount")
        if value in (None, ""):
            return None
        percent = D(str(value))
        return (
            percent
            if percent <= discount_limit(unit, price, invoice.warehouse_id)["percent"]
            else None
        )
    if "discount_percent" in data:
        value = data.get("discount_percent")
        return None if value in (None, "") else D(str(value))
    client_percent = invoice.client.discount_percent if invoice.client_id else None
    if not client_percent:
        return None
    limit = discount_limit(unit, price, invoice.warehouse_id)
    return client_percent if client_percent <= limit["percent"] else None


def _add_lines(invoice: Invoice, lines: list[LineData]) -> None:
    position = 0
    for data in lines:
        combo = (
            catalog.get_item(getattr(data.get("item"), "pk", data.get("item")))
            if data.get("item")
            else None
        )
        if combo is None or combo.kind != Kind.COMBO:
            _unit_line(invoice, data, position).save()
            position += 1
            continue
        times = D(str(data.get("quantity") or 1))
        if times <= 0:
            raise InvoiceError(f"«{combo}»: количество должно быть больше нуля.")
        parts = catalog.expand_combination(combo)
        header = None
        if not combo.is_template:  # одной строкой: заголовок + состав
            header = InvoiceLine(
                invoice=invoice,
                item=combo,
                quantity=times,
                price=ZERO,
                position=position,
                performer_id=getattr(data.get("performer"), "pk", data.get("performer"))
                or invoice.doctor_id,
            )
            header.save()
            position += 1
        for part in parts:
            child: LineData = {
                "item_unit": part["item_unit"],
                "quantity": part["quantity"] * times,
                "performer": data.get("performer"),
            }
            # Скидка на комбинацию — каждой позиции состава в её пределах
            # (товары и услуги — свои лимиты); где не проходит — без скидки.
            discount = _combo_discount_for(part["item_unit"], data)
            if discount is not None:
                child["combo_discount"] = discount
            line = _unit_line(
                invoice,
                child,
                position,
                parent=header,
                override=part["price"],
            )
            line.save()
            position += 1


# --- Скидки и суммы ----------------------------------------------------------------


def recalculate(invoice: Invoice) -> None:
    """Скидки и суммы.

    - скидка строки в процентах — в пределах лимита клиники для товара или услуги и так,
      чтобы цена не опустилась ниже себестоимости; иначе — понятная ошибка;
    - скидка суммой на счёт делится пропорционально между строками без своей скидки
      и без ручной цены (копейки остатка — на последнюю); на каждой из них она тоже
      должна укладываться в предел;
    - строка с ручной ценой — без скидки.
    """
    lines = list(invoice.lines.select_related("item", "item_unit"))
    leaves = [line for line in lines if not any(child.parent_id == line.pk for child in lines)]
    for line in leaves:
        line.discount = ZERO
        if line.manual_price:
            line.discount_percent = None
    for line in leaves:
        percent = line.discount_percent
        if percent is None or line.item_unit is None:
            continue
        if not ZERO <= percent <= 100:
            raise InvoiceError(f"«{line.item}»: скидка — от 0 до 100 %.")
        limit = discount_limit(line.item_unit, line.price, invoice.warehouse_id)
        if percent > limit["percent"]:
            raise _limit_error(line.item, percent, limit)
        line.discount = _money(line.price * line.quantity * percent / 100)
    eligible = [line for line in leaves if not line.manual_price and line.discount_percent is None]
    eligible_gross = sum((line.price * line.quantity for line in eligible), ZERO)
    target = invoice.discount_amount or ZERO
    if target < 0 or target > eligible_gross:
        raise InvoiceError(
            "Скидка суммой не может быть больше суммы строк, на которые она действует "
            "(строки без своей скидки и без ручной цены)."
        )
    rest = target
    for index, line in enumerate(eligible):
        gross = line.price * line.quantity
        share = (
            rest
            if index == len(eligible) - 1
            else _money(target * gross / eligible_gross)
            if eligible_gross
            else ZERO
        )
        line.discount = min(share, _money(gross))
        rest -= line.discount
        if line.discount and line.item_unit is not None and gross:
            effective = (line.discount / gross * 100).quantize(Decimal("0.01"))
            limit = discount_limit(line.item_unit, line.price, invoice.warehouse_id)
            if effective > limit["percent"]:
                raise _limit_error(line.item, effective, limit, "скидка суммой даёт")
    for line in leaves:
        line.amount = _money(line.price * line.quantity - line.discount)
        line.save(update_fields=["discount", "discount_percent", "amount"])
    for header in (line for line in lines if line not in leaves):
        children = [line for line in leaves if line.parent_id == header.pk]
        header.amount = sum((c.amount for c in children), ZERO)
        header.discount = sum((c.discount for c in children), ZERO)
        header.price = _money(header.amount / header.quantity) if header.quantity else ZERO
        header.save(update_fields=["amount", "discount", "price"])
    invoice.subtotal = _money(sum((line.price * line.quantity for line in leaves), ZERO))
    invoice.discount_total = sum((line.discount for line in leaves), ZERO)
    invoice.total = invoice.subtotal - invoice.discount_total
    invoice.save(update_fields=["subtotal", "discount_total", "total"])


@transaction.atomic
def save_invoice(invoice: Invoice, lines: list[LineData] | None = None) -> Invoice:
    """Сохранить черновик счёта: строки (если переданы), скидки, суммы."""
    pet = invoice.pet
    if pet is not None and clients.current_owner(pet).pk != invoice.client_id:
        raise InvoiceError("Питомец принадлежит другому клиенту.")
    if invoice.warehouse_id is None:
        invoice.warehouse = inventory.default_sale_warehouse()
    elif not inventory.sale_warehouses().filter(pk=invoice.warehouse_id).exists():
        raise InvoiceError(
            "По счёту товар списывается только со склада продажи (оперативного), "
            "а не со склада хранения."
        )
    invoice.save()
    if lines is not None:
        invoice.lines.all().delete()
        _add_lines(invoice, lines)
    recalculate(invoice)
    return invoice


# --- Выполнение и откат --------------------------------------------------------------


def execute_invoice(invoice: Invoice) -> None:
    """Выполнить счёт (из core.services.execute_document, в транзакции):
    списать товар по партиям, записать себестоимость, начислить долг клиенту."""
    lines = list(invoice.lines.select_related("item", "item_unit"))
    if not lines:
        raise InvoiceError("В счёте нет позиций.")
    leaves = [line for line in lines if line.item_unit_id is not None]
    for line in leaves:
        item = line.item
        if item.kind == Kind.GOODS and item.stock_tracked:
            try:
                written = inventory.write_off(
                    [{"item": item, "qty_base": line.qty_base, "warehouse": invoice.warehouse_id}],
                    invoice,
                )
            except inventory.StockError as error:
                raise InvoiceError(f"{error} Оформите приход или выберите другой склад.") from error
            InvoiceLineBatch.objects.bulk_create(
                InvoiceLineBatch(
                    line=line, batch=w.batch, qty_base=w.qty, cost_per_base=w.cost_per_base
                )
                for w in written
            )
            line.cost = _money(sum((w.qty * w.cost_per_base for w in written), ZERO))
        else:  # услуга или товар без складского учёта — себестоимость из карточки
            line.cost = _money((item.manual_cost or ZERO) * line.qty_base)
        line.save(update_fields=["cost"])
    for header in (line for line in lines if line.item_unit_id is None):
        header.cost = sum((c.cost for c in leaves if c.parent_id == header.pk), ZERO)
        header.save(update_fields=["cost"])
    clients.charge(invoice.client_id, invoice.total, invoice)
    invoice.paid_amount = ZERO
    # Аванс клиента идёт в оплату нового счёта — по событию «выполнен» (см. apps.py),
    # когда счёт уже в статусе «выполнен».


def rollback_invoice(invoice: Invoice) -> None:
    """Откат в черновик: товар — обратно на склад, начисление клиенту — снять.

    Оплаты по счёту никуда не пропадают: деньги остаются на балансе клиента авансом —
    исправленный счёт оплатится из него, или аванс вернут деньгами.
    """
    inventory.reverse(invoice)
    clients.reverse_charges(invoice)
    InvoiceLineBatch.objects.filter(line__invoice=invoice).delete()
    invoice.lines.update(cost=ZERO)
    InvoicePayment.objects.filter(invoice=invoice).delete()
    invoice.paid_amount = ZERO


# --- Счёт из медкарты ----------------------------------------------------------------


@transaction.atomic
def invoice_for_visit(visit: Any) -> Invoice:
    """Счёт по записи медкарты: черновик с отмеченными через «@» позициями.

    Черновик по этой записи уже есть — в него добавляются позиции, которых в нём ещё нет.
    """
    invoice = Invoice.objects.filter(visit_id=visit.pk, status=Document.Status.DRAFT).first()
    wanted = [line for line in _visit_lines(visit)]
    if invoice is None:
        invoice = Invoice(
            client_id=visit.client_id,
            pet_id=visit.pet_id,
            doctor_id=visit.doctor_id,
            appointment_id=visit.appointment_id,
            visit_id=visit.pk,
        )
        return save_invoice(invoice, wanted)
    present = {str(line.item_unit_id) for line in invoice.lines.all()}
    current: list[LineData] = [
        {
            "item_unit": line.item_unit_id,
            "quantity": line.quantity,
            "price": line.price if line.manual_price else None,
            "performer": line.performer_id,
        }
        for line in invoice.lines.filter(parent=None).exclude(item_unit=None)
    ]
    current += [line for line in wanted if str(line["item_unit"]) not in present]
    return save_invoice(invoice, current)


def _visit_lines(visit: Any) -> list[LineData]:
    from medical import services as medical

    return medical.invoice_lines(visit)  # type: ignore[return-value]


# --- Отчёты ------------------------------------------------------------------------


class PerformerRow(TypedDict):
    performer: str | None
    name: str
    lines: int
    amount: Decimal
    cost: Decimal


def revenue_by_performer(date_from: date, date_to: date) -> list[PerformerRow]:
    """Выручка по исполнителям — по строкам выполненных счетов за период (без заголовков
    комбинаций: считаются строки состава)."""
    zone = timezone.get_current_timezone()
    start = datetime.combine(date_from, datetime.min.time(), zone)
    end = datetime.combine(date_to, datetime.min.time(), zone) + timedelta(days=1)
    rows = (
        InvoiceLine.objects.filter(
            invoice__status=Document.Status.EXECUTED,
            invoice__is_deleted=False,
            invoice__date__gte=start,
            invoice__date__lt=end,
        )
        .exclude(item_unit=None)
        .values("performer", "performer__last_name", "performer__first_name", "performer__username")
        .annotate(lines=Count("id"), amount=Sum("amount"), cost=Sum("cost"))
        .order_by("-amount")
    )
    result: list[PerformerRow] = []
    for r in rows:
        name = " ".join(p for p in (r["performer__last_name"], r["performer__first_name"]) if p)
        result.append(
            {
                "performer": str(r["performer"]) if r["performer"] else None,
                "name": name or r["performer__username"] or "без исполнителя",
                "lines": r["lines"],
                "amount": r["amount"] or ZERO,
                "cost": r["cost"] or ZERO,
            }
        )
    return result


def client_invoices(client: Any) -> Any:
    return Invoice.objects.filter(client=client).order_by("-date")


# --- Подбор позиций и печать --------------------------------------------------------


def lookup(text: str = "", barcode: str = "", warehouse: Any = None) -> list[dict[str, Any]]:
    """Позиции для счёта: по штрихкоду или словам названия; с ценой и остатком.

    Остаток — склада счёта, а если он не задан — склада продажи (оперативного):
    продают только с него, остаток основного склада здесь не нужен.
    """
    if warehouse is None:
        default = inventory.default_sale_warehouse()
        warehouse = default.pk if default else None
    if barcode:
        unit = catalog.find_by_barcode(barcode)
        units = [unit] if unit is not None else []
        combos: list[Item] = []
    else:
        if len(text.strip()) < 2:
            return []
        items = catalog.search_items(Item.objects.filter(is_active=True, for_sale=True), text)[:20]
        units = [
            u
            for item in items
            if item.kind != Kind.COMBO and not item.combo_only
            for u in item.units.select_related("item", "unit").filter(for_sale=True)
        ]
        combos = [item for item in items if item.kind == Kind.COMBO]
    result: list[dict[str, Any]] = []
    for unit in units:
        if not unit.for_sale or unit.item.combo_only:
            continue
        tracked = unit.item.kind == Kind.GOODS and unit.item.stock_tracked
        on_hand = inventory.available(unit.item, warehouse) if tracked else None
        price = list_price(unit, warehouse)
        limit = discount_limit(unit, price, warehouse) if price is not None else None
        result.append(
            {
                "max_discount": str(limit["percent"]) if limit else None,
                "max_reason": limit["reason"] if limit else None,
                "unit_cost": str(limit["cost"]) if limit and limit["cost"] is not None else None,
                "cost_source": limit["cost_source"] if limit else "",
                "item_unit": str(unit.pk),
                "item": str(unit.item_id),
                "kind": unit.item.kind,
                "name": unit.item.name,
                "unit": unit.unit.name,
                "price": str(price) if price is not None else None,
                "price_min": str(unit.price_min) if unit.price_min is not None else None,
                "price_max": str(unit.price_max) if unit.price_max is not None else None,
                "stock": str(on_hand / unit.ratio) if on_hand is not None else None,
                # Остаток словами: «5,25 упак. / 5 упак. 2 таб.».
                "stock_text": catalog.qty_text(unit.item, on_hand) if on_hand is not None else None,
            }
        )
    for combo in combos:
        price = catalog.combination_price(combo)
        result.append(
            {
                "max_discount": None,
                "max_reason": None,
                "unit_cost": None,
                "cost_source": "",
                "item_unit": None,
                "item": str(combo.pk),
                "kind": "combo",
                "name": combo.name,
                "unit": "компл.",
                "price": str(price) if price is not None else None,
                "price_min": None,
                "price_max": None,
                "stock": None,
                "stock_text": None,
            }
        )
    return result


def print_context(invoice: Invoice) -> dict[str, Any]:
    """Данные печатной формы «Счёт»: строки с учётом режима печати комбинаций."""
    lines = list(invoice.lines.select_related("item", "item_unit__unit", "performer"))
    printed: list[dict[str, Any]] = []
    for line in lines:
        if line.parent_id is not None:
            continue
        row = {
            "name": line.item.name,
            "unit": line.item_unit.unit.name if line.item_unit else "компл.",
            "quantity": line.quantity,
            "price": line.price,
            "discount": line.discount,
            "discount_percent": line.discount_percent,
            "amount": line.amount,
            "composition": [],
        }
        if line.item_unit is None:  # комбинация одной строкой
            children = [c for c in lines if c.parent_id == line.pk]
            mode = line.item.print_mode
            if mode == "full":
                row["composition"] = [
                    {
                        "name": c.item.name,
                        "quantity": c.quantity,
                        "price": c.price,
                        "amount": c.amount,
                    }
                    for c in children
                ]
            elif mode == "composition":
                row["composition"] = [
                    {"name": c.item.name, "quantity": c.quantity} for c in children
                ]
            elif mode == "services":
                row["composition"] = [
                    {
                        "name": c.item.name,
                        "quantity": c.quantity,
                        "price": c.price,
                        "amount": c.amount,
                    }
                    for c in children
                    if c.item.kind == Kind.SERVICE
                ]
        printed.append(row)
    return {
        "invoice": {
            "number": invoice.number,
            "date": invoice.date,
            "subtotal": invoice.subtotal,
            "discount": invoice.discount_total,
            "total": invoice.total,
            "status": invoice.get_status_display(),
        },
        "client": {"full_name": invoice.client.full_name},
        "pet": {"name": invoice.pet.name if invoice.pet else ""},
        "doctor": {"short_name": invoice.doctor.short_name if invoice.doctor else ""},
        "lines": printed,
    }


def sample_print_context() -> dict[str, Any]:
    return {
        "invoice": {
            "number": "K1-000123",
            "date": timezone.now(),
            "subtotal": D("2400"),
            "discount": D("140"),
            "total": D("2260"),
            "status": "выполнен",
        },
        "client": {"full_name": "Иванова Анна Петровна"},
        "pet": {"name": "Барсик"},
        "doctor": {"short_name": "Петров П. П."},
        "lines": [
            {
                "name": "Первичный приём",
                "unit": "усл.",
                "quantity": D("1"),
                "price": D("1000"),
                "discount": D("0"),
                "amount": D("1000"),
                "composition": [],
            },
            {
                "name": "Фелиферон",
                "unit": "фл.",
                "quantity": D("2"),
                "price": D("700"),
                "discount": D("140"),
                "amount": D("1260"),
                "composition": [],
            },
        ],
    }


# --- Оплата счетов (для кассы) --------------------------------------------------------


def unpaid_invoices(client: Any) -> QuerySet[Invoice]:
    """Выполненные счета клиента, оплаченные не полностью — старые первыми."""
    return (
        Invoice.objects.filter(client=client, status=Invoice.Status.EXECUTED)
        .filter(paid_amount__lt=F("total"))
        .order_by("date", "number")
    )


def client_credit(client: Any) -> Decimal:
    """Деньги клиента, ещё не распределённые на счета (аванс).

    Журнал баланса = начислено по счетам − оплачено + возвращено. Нераспределённое =
    неоплаченный остаток счетов − баланс журнала (см. PROJECT_PLAN, 6.6).
    """
    unpaid = sum((i.unpaid for i in unpaid_invoices(client)), ZERO)
    return _money(unpaid + clients.balance(client))


def _set_paid(invoice: Invoice) -> None:
    paid = invoice.payments.aggregate(total=Sum("amount"))["total"] or ZERO
    invoice.paid_amount = _money(paid)
    invoice.save(update_fields=["paid_amount"])


@transaction.atomic
def allocate_credit(
    client: Any, invoice_ids: list[Any] | None = None, payment_id: Any = None
) -> Decimal:
    """Распределить деньги клиента на неоплаченные счета: сначала указанные, затем — никакие
    другие (если указаны) или все по порядку (если не указаны). Возвращает распределённое."""
    credit = client_credit(client)
    if credit <= 0:
        return ZERO
    invoices = list(unpaid_invoices(client))
    if invoice_ids is not None:
        wanted = {str(pk) for pk in invoice_ids}
        invoices = [i for i in invoices if str(i.pk) in wanted]
    allocated = ZERO
    for invoice in invoices:
        if credit <= 0:
            break
        amount = min(invoice.unpaid, credit)
        if amount <= 0:
            continue
        InvoicePayment.objects.create(invoice=invoice, amount=amount, payment_id=payment_id)
        _set_paid(invoice)
        credit -= amount
        allocated += amount
    return allocated


@transaction.atomic
def release_payment(client: Any, payment_id: Any) -> None:
    """Возврат оплаты: снять её распределения; если денег стало меньше, чем распределено
    зачётами аванса, снять и их — с самых новых."""
    touched = {p.invoice_id for p in InvoicePayment.objects.filter(payment_id=payment_id)}
    InvoicePayment.objects.filter(payment_id=payment_id).delete()
    for invoice in Invoice.objects.filter(pk__in=touched):
        _set_paid(invoice)
    while client_credit(client) < 0:
        last = (
            InvoicePayment.objects.filter(invoice__client=client)
            .order_by("-created_at", "-id")
            .first()
        )
        if last is None:
            break
        shortage = -client_credit(client)
        if last.amount > shortage:
            last.amount -= shortage
            last.save(update_fields=["amount"])
        else:
            last.delete()
        _set_paid(last.invoice)


@transaction.atomic
def update_details(
    invoice: Invoice,
    doctor: Any = ...,
    pet: Any = ...,
    performers: dict[str, Any] | None = None,
) -> Invoice:
    """Поправить в выполненном счёте врача, питомца и исполнителей строк — без отката.

    Это не меняет денег и остатков, а каждое изменение остаётся в журнале аудита.
    """
    fields = []
    if doctor is not ...:
        invoice.doctor_id = getattr(doctor, "pk", doctor)
        fields.append("doctor")
    if pet is not ...:
        pet_id = getattr(pet, "pk", pet)
        if pet_id and clients.current_owner_id(pet_id) != invoice.client_id:
            raise InvoiceError("Питомец принадлежит другому клиенту.")
        invoice.pet_id = pet_id
        fields.append("pet")
    if fields:
        invoice.save(update_fields=fields)
    for line_id, user in (performers or {}).items():
        invoice.lines.filter(pk=line_id).update(performer_id=getattr(user, "pk", user))
    return invoice


# --- Отчёты ------------------------------------------------------------------------


def _period(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    zone = timezone.get_current_timezone()
    start = datetime.combine(date_from, datetime.min.time(), zone)
    return start, datetime.combine(date_to, datetime.min.time(), zone) + timedelta(days=1)


def _executed(date_from: date, date_to: date) -> QuerySet[Invoice]:
    start, end = _period(date_from, date_to)
    return Invoice.objects.filter(status=Document.Status.EXECUTED, date__gte=start, date__lt=end)


def sales_by_day(date_from: date, date_to: date) -> list[dict[str, Any]]:
    """Продажи по дням: счетов, сумма до скидки, скидка, к оплате, себестоимость."""
    from django.db.models.functions import TruncDate

    zone = timezone.get_current_timezone()
    by_day = (
        _executed(date_from, date_to)
        .annotate(day=TruncDate("date", tzinfo=zone))
        .values("day")
        .annotate(
            n=Count("id"), sum_subtotal=Sum("subtotal"), sum_discount=Sum("discount_total"),
            sum_total=Sum("total"),
        )
        .order_by("day")
    )  # fmt: skip
    start, end = _period(date_from, date_to)
    costs = {
        r["day"]: r["cost"] or ZERO
        for r in InvoiceLine.objects.filter(
            invoice__status=Document.Status.EXECUTED,
            invoice__date__gte=start,
            invoice__date__lt=end,
        )
        .exclude(item_unit=None)
        .annotate(day=TruncDate("invoice__date", tzinfo=zone))
        .values("day")
        .annotate(cost=Sum("cost"))
    }
    return [
        {
            "day": r["day"], "invoices": r["n"], "subtotal": r["sum_subtotal"] or ZERO,
            "discount": r["sum_discount"] or ZERO, "total": r["sum_total"] or ZERO,
            "cost": costs.get(r["day"], ZERO),
        }
        for r in by_day
    ]  # fmt: skip


def top_items(
    date_from: date, date_to: date, kind: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """Популярные услуги и товары за период: количество, выручка, себестоимость."""
    start, end = _period(date_from, date_to)
    lines = InvoiceLine.objects.filter(
        invoice__status=Document.Status.EXECUTED, invoice__date__gte=start, invoice__date__lt=end
    ).exclude(item_unit=None)
    if kind:
        lines = lines.filter(item__kind=kind)
    rows = (
        lines.values("item", "item__name", "item__kind", "item__base_unit__name")
        .annotate(
            quantity=Sum("qty_base"),
            amount=Sum("amount"),
            cost=Sum("cost"),
            invoices=Count("invoice", distinct=True),
        )
        .order_by("-amount")[:limit]
    )
    return [
        {
            "item": str(r["item"]), "name": r["item__name"], "kind": r["item__kind"],
            "unit": r["item__base_unit__name"], "quantity": r["quantity"] or ZERO,
            "amount": r["amount"] or ZERO, "cost": r["cost"] or ZERO, "invoices": r["invoices"],
        }
        for r in rows
    ]  # fmt: skip


def debtors() -> list[dict[str, Any]]:
    """Должники: у кого есть неоплаченные выполненные счета.

    Сумма долга, сколько счетов, дата самого старого неоплаченного.
    """
    by_client: dict[Any, dict[str, Any]] = {}
    unpaid = (
        Invoice.objects.filter(status=Document.Status.EXECUTED, paid_amount__lt=F("total"))
        .exclude(client__is_guest=True)
        .select_related("client")
        .prefetch_related("client__phones")
        .order_by("date")
    )
    for invoice in unpaid:
        row = by_client.setdefault(
            invoice.client_id,
            {
                "client": str(invoice.client_id), "name": invoice.client.full_name,
                "phone": next((p.number for p in invoice.client.phones.all()), ""),
                "debt": ZERO, "invoices": 0, "since": timezone.localdate(invoice.date),
            },
        )  # fmt: skip
        row["debt"] += invoice.unpaid
        row["invoices"] += 1
    return sorted(by_client.values(), key=lambda r: -r["debt"])


def create_invoice(
    client: Any, lines: list[LineData], pet: Any = None, doctor: Any = None, comment: str = ""
) -> Any:
    """Черновик счёта от другого модуля (например, стационара). Возвращает id счёта."""
    invoice = save_invoice(
        Invoice(client_id=getattr(client, "pk", client), pet_id=getattr(pet, "pk", pet),
                doctor_id=getattr(doctor, "pk", doctor), comment=comment),
        lines,
    )  # fmt: skip
    return invoice.pk
