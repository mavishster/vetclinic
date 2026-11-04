"""Касса: публичный вход модуля.

Отвечает за: кассы, кассовые документы, оплаты, закрытие кассы, ККТ.

Другие модули обращаются к модулю только через функции этого файла.
Бизнес-правила живут здесь, а не в моделях и не в API (ENGINEERING.md).
"""

from decimal import Decimal
from typing import Any, TypedDict

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from billing import services as billing
from cash.models import CashMovement, CashOperation, CashRegister, CashShift, Payment
from clients import services as clients
from core import printing
from core import services as core

ZERO = Decimal("0")
K = CashRegister.Kind


class CashError(Exception):
    """Кассовая операция невозможна. Текст — для пользователя."""


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


# --- Смены и остатки ---------------------------------------------------------------


def open_shift(register: Any) -> CashShift:
    """Открытая смена кассы; нет — открывается (смена начинается с первой операции)."""
    register_id = getattr(register, "pk", register)
    shift = (
        CashShift.objects.select_for_update()
        .filter(register_id=register_id, closed_at=None)
        .first()
    )
    return shift or CashShift.objects.create(register_id=register_id, opened_at=timezone.now())


def balance(register: Any) -> Decimal:
    """Сколько денег в кассе."""
    total = CashMovement.objects.filter(register=register).aggregate(total=Sum("amount"))["total"]
    return _money(total if total is not None else ZERO)


def _move(document: Any, register: Any, amount: Decimal, note: str) -> None:
    if amount == 0:
        return
    core.post_entry(
        CashMovement,
        document,
        register_id=getattr(register, "pk", register),
        shift=open_shift(register),
        amount=amount,
        note=note,
    )


@transaction.atomic
def close_shift(register: CashRegister, user: Any) -> CashShift:
    """Закрыть кассу: итоги смены. Следующая операция откроет новую смену."""
    shift = CashShift.objects.select_for_update().filter(register=register, closed_at=None).first()
    if shift is None:
        raise CashError("Смена этой кассы не открыта — операций с последнего закрытия не было.")
    moves = shift.movements.all()
    shift.income = moves.filter(amount__gt=0).aggregate(t=Sum("amount"))["t"] or ZERO
    shift.expense = -(moves.filter(amount__lt=0).aggregate(t=Sum("amount"))["t"] or ZERO)
    shift.closing_balance = balance(register)
    shift.closed_at = timezone.now()
    shift.closed_by = user
    shift.save()
    return shift


def _shifts_open(document: Any) -> bool:
    return all(
        m.shift.closed_at is None
        for m in core.entries_of(CashMovement, document).select_related("shift")
    )


# --- Оплата -------------------------------------------------------------------------


def execute_payment(payment: Payment) -> None:
    """Проводки оплаты: деньги в кассы, баланс клиента, распределение на счета."""
    for field in ("cash_received", "change_given", "card_amount"):
        if getattr(payment, field) < 0:
            raise CashError("Суммы оплаты не могут быть отрицательными.")
    if payment.change_given > payment.cash_received:
        raise CashError("Сдача не может быть больше полученных наличных.")
    if payment.amount <= 0:
        raise CashError("Сумма оплаты должна быть больше нуля.")
    if payment.cash_received and (
        payment.cash_register is None or payment.cash_register.kind != K.CASH
    ):
        raise CashError("Выберите кассу наличных.")
    if payment.card_amount and (
        payment.card_register is None or payment.card_register.kind != K.CASHLESS
    ):
        raise CashError("Выберите кассу безнала (терминал).")
    if payment.cash_received:
        _move(
            payment, payment.cash_register, payment.cash_received - payment.change_given, "оплата"
        )
    if payment.card_amount:
        _move(payment, payment.card_register, payment.card_amount, "оплата безналом")
    clients.pay(payment.client_id, payment.amount, payment)


def after_payment(payment: Payment) -> Payment:
    """После выполнения: распределить деньги клиента на выбранные счета (и только на них;
    без счетов — это аванс, он сам зачтётся в следующие счета)."""
    if payment.invoice_ids:
        payment.allocated = billing.allocate_credit(
            payment.client_id, payment.invoice_ids, payment.pk
        )
    return payment


def rollback_payment(payment: Payment) -> None:
    """Возврат оплаты — только пока смена кассы открыта; деньги уходят из кассы,
    счета снова становятся неоплаченными."""
    if not _shifts_open(payment):
        raise CashError(
            "Касса уже закрыта — вернуть эту оплату нельзя. Сделайте откат счёта и верните аванс."
        )
    core.reverse_entries(CashMovement, payment)
    clients.reverse_charges(payment)
    billing.release_payment(payment.client_id, payment.pk)


class PaymentData(TypedDict, total=False):
    client: Any
    invoice_ids: list[Any]
    cash_register: Any
    card_register: Any
    cash_received: Decimal
    card_amount: Decimal
    change_to_balance: bool


@transaction.atomic
def pay(data: PaymentData) -> Payment:
    """Принять оплату: создать документ, выполнить и распределить на счета.

    Сдача = получено наличными + безнал − к оплате по выбранным счетам (с учётом аванса).
    change_to_balance — не выдавать сдачу, а оставить авансом на балансе клиента.
    """
    client = data["client"]
    invoice_ids = [str(pk) for pk in data.get("invoice_ids") or []]
    due = sum((i.unpaid for i in billing.unpaid_invoices(client) if str(i.pk) in invoice_ids), ZERO)
    due = max(due - billing.client_credit(client), ZERO)  # аванс уже покрывает часть
    received = _money(Decimal(str(data.get("cash_received") or 0)))
    card = _money(Decimal(str(data.get("card_amount") or 0)))
    if card > due and invoice_ids:
        raise CashError("Безналом нельзя заплатить больше, чем к оплате — сдачу с карты не выдают.")
    guest = clients.is_guest(client)
    if guest and received + card < due:
        raise CashError("Быстрый счёт оплачивается полностью — у гостя не бывает долга.")
    if guest and data.get("change_to_balance"):
        raise CashError("У гостя нет баланса — сдачу нужно выдать.")
    change = (
        ZERO
        if data.get("change_to_balance") or not invoice_ids
        else max(received + card - due, ZERO)
    )
    payment = Payment(
        client=client,
        invoice_ids=invoice_ids,
        cash_register_id=_pk(data.get("cash_register")),
        card_register_id=_pk(data.get("card_register")),
        cash_received=received,
        change_given=min(change, received),
        card_amount=card,
    )
    payment.save()
    core.execute_document(payment)
    after_payment(payment)
    # «Распределено» — справочная сумма; выполненный документ не правится, поэтому через update.
    Payment.objects.filter(pk=payment.pk).update(allocated=payment.allocated)
    return payment


def _pk(value: Any) -> Any:
    return getattr(value, "pk", value) or None


def use_advance(client: Any, invoice_ids: list[Any]) -> Decimal:
    """Оплатить счета авансом клиента — без денег (например, после отката счёта)."""
    return billing.allocate_credit(client, invoice_ids)


# --- Кассовые операции --------------------------------------------------------------


def execute_operation(operation: CashOperation) -> None:
    if operation.amount <= 0:
        raise CashError("Сумма должна быть больше нуля.")
    kind = operation.kind
    if kind == CashOperation.Kind.INCOME:
        _move(operation, operation.register, operation.amount, operation.purpose or "внесение")
    elif kind == CashOperation.Kind.EXPENSE:
        _check_enough(operation.register, operation.amount)
        _move(operation, operation.register, -operation.amount, operation.purpose or "выдача")
    elif kind == CashOperation.Kind.TRANSFER:
        if operation.target_register_id in (None, operation.register_id):
            raise CashError("Выберите другую кассу, в которую перемещаются деньги.")
        _check_enough(operation.register, operation.amount)
        _move(operation, operation.register, -operation.amount, "перемещение")
        _move(operation, operation.target_register, operation.amount, "перемещение")
    elif kind == CashOperation.Kind.ADVANCE_RETURN:
        if operation.client_id is None:
            raise CashError("Выберите клиента.")
        if operation.register.kind != K.CASH:
            raise CashError("Аванс возвращается наличными — выберите кассу наличных.")
        # Вернуть можно только чистый аванс: долги по счетам сначала гасятся им.
        advance = max(clients.balance(operation.client_id), ZERO)
        if operation.amount > advance:
            raise CashError(f"У клиента аванс {printing.money(advance)} — вернуть больше нельзя.")
        _check_enough(operation.register, operation.amount)
        _move(operation, operation.register, -operation.amount, "возврат аванса")
        clients.charge(operation.client_id, operation.amount, operation)
    else:
        raise CashError("Неизвестный вид операции.")


def _check_enough(register: Any, amount: Decimal) -> None:
    left = balance(register)
    if amount > left:
        raise CashError(
            f"В кассе только {printing.money(left)} — выдать {printing.money(amount)} нельзя."
        )


def rollback_cash_document(document: Any) -> None:
    if not _shifts_open(document):
        raise CashError("Касса уже закрыта — эту операцию отменить нельзя.")
    core.reverse_entries(CashMovement, document)
    clients.reverse_charges(document)


@transaction.atomic
def operate(operation: CashOperation, user: Any, pin: str | None = None) -> CashOperation:
    """Провести кассовую операцию. Возврат аванса — с подтверждением ПИН-кодом."""
    if operation.kind == CashOperation.Kind.ADVANCE_RETURN:
        try:
            core.confirm_action(user, pin or "")
        except core.PinError as error:
            raise CashError(str(error)) from error
    operation.save()
    return core.execute_document(operation)


# --- Сводка -------------------------------------------------------------------------


class RegisterRow(TypedDict):
    id: str
    name: str
    kind: str
    balance: Decimal
    shift_opened_at: Any
    shift_income: Decimal
    shift_expense: Decimal


def summary() -> list[RegisterRow]:
    """Кассы: остаток и итоги открытой смены."""
    rows: list[RegisterRow] = []
    for register in CashRegister.objects.filter(is_active=True).order_by("name"):
        shift = CashShift.objects.filter(register=register, closed_at=None).first()
        moves = shift.movements.all() if shift else CashMovement.objects.none()
        rows.append(
            {
                "id": str(register.pk),
                "name": register.name,
                "kind": register.kind,
                "balance": balance(register),
                "shift_opened_at": shift.opened_at if shift else None,
                "shift_income": moves.filter(amount__gt=0).aggregate(t=Sum("amount"))["t"] or ZERO,
                "shift_expense": -(
                    moves.filter(amount__lt=0).aggregate(t=Sum("amount"))["t"] or ZERO
                ),
            }
        )
    return rows


# --- Отчёты ------------------------------------------------------------------------


def money_by_day(date_from: Any, date_to: Any) -> list[dict[str, Any]]:
    """Деньги по дням: поступило наличными и безналом, выдано (возвраты, расходы)."""
    from datetime import datetime, timedelta

    from django.db.models import Q
    from django.db.models.functions import TruncDate

    zone = timezone.get_current_timezone()
    start = datetime.combine(date_from, datetime.min.time(), zone)
    end = datetime.combine(date_to, datetime.min.time(), zone) + timedelta(days=1)
    from django.contrib.contenttypes.models import ContentType

    # Поступило — только оплаты клиентов (внесение размена и перемещения между кассами —
    # не выручка); выдано — возвраты, возврат аванса и расходы, без перемещений.
    payment = ContentType.objects.get_for_model(Payment)
    is_payment = Q(document_type=payment, amount__gt=0)
    rows = (
        CashMovement.objects.effective()
        .filter(posted_at__gte=start, posted_at__lt=end)
        .annotate(day=TruncDate("posted_at", tzinfo=zone))
        .values("day")
        .annotate(
            cash_in=Sum("amount", filter=is_payment & Q(register__kind=K.CASH)),
            card_in=Sum("amount", filter=is_payment & Q(register__kind=K.CASHLESS)),
            out=Sum("amount", filter=Q(amount__lt=0) & ~Q(note="перемещение")),
        )
        .order_by("day")
    )
    return [
        {"day": r["day"], "cash_in": r["cash_in"] or ZERO, "card_in": r["card_in"] or ZERO,
         "out": -(r["out"] or ZERO)}
        for r in rows
    ]  # fmt: skip
