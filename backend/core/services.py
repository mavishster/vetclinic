"""Ядро: публичный вход модуля.

Отвечает за: базовые модели, документы, журнал движений, справочники, права,
аудит, нумерацию, печать.

Другие модули обращаются к модулю только через функции этого файла.
Бизнес-правила живут здесь, а не в моделях и не в API (ENGINEERING.md).
"""

import itertools
from datetime import timedelta
from typing import Any, TypedDict

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import DatabaseError, connection, transaction
from django.db.models import QuerySet
from django.utils import timezone

from core import events, numbering, printing
from core.context import get_current_user
from core.models import Clinic, Document, DocumentError, LedgerEntry, PrintTemplate, User


class HealthStatus(TypedDict):
    status: str
    database: bool


def health() -> HealthStatus:
    """Проверка работоспособности: отвечает ли приложение и доступна ли база."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        database_ok = True
    except DatabaseError:
        database_ok = False
    return {"status": "ok" if database_ok else "degraded", "database": database_ok}


def current_clinic() -> Clinic:
    """Клиника, в которой работает система.

    В первой версии клиника одна (создаётся миграцией). Когда появится второй
    филиал, здесь будет выбор по пользователю или узлу — вызывающий код не изменится.
    """
    clinic = Clinic.objects.order_by("created_at").first()
    if clinic is None:
        raise Clinic.DoesNotExist("Клиника не создана: примените миграции ядра.")
    return clinic


# --- ПИН-код для подтверждения операций (ADR-014) ---------------------------------


class PinError(Exception):
    """Подтверждение ПИН-кодом не прошло. Текст — для пользователя."""


def _is_trivial_pin(pin: str) -> bool:
    """0000, 1111, 1234, 4321 и подобные угадываются первыми."""
    digits = [int(d) for d in pin]
    steps = {b - a for a, b in itertools.pairwise(digits)}
    return steps in ({0}, {1}, {-1})


def set_pin(user: User, pin: str) -> None:
    """Задать или сменить ПИН: 4–6 цифр, не слишком простой."""
    if not (pin.isdigit() and 4 <= len(pin) <= 6):
        raise PinError("ПИН должен состоять из 4–6 цифр.")
    if _is_trivial_pin(pin):
        raise PinError("ПИН слишком простой: не используйте одинаковые цифры или 1234.")
    user.pin_hash = make_password(pin)
    user.pin_failed_attempts = 0
    user.pin_locked_until = None
    user.save(update_fields=["pin_hash", "pin_failed_attempts", "pin_locked_until"])


def reset_pin(user: User) -> None:
    """Сбросить ПИН (например, сотрудник его забыл). Задать новый сможет сам сотрудник."""
    user.pin_hash = ""
    user.pin_failed_attempts = 0
    user.pin_locked_until = None
    user.save(update_fields=["pin_hash", "pin_failed_attempts", "pin_locked_until"])


def confirm_action(user: User, pin: str) -> None:
    """Проверить ПИН перед важной операцией. При ошибке — PinError с понятным текстом.

    После settings.PIN_MAX_ATTEMPTS неверных попыток ПИН блокируется
    на settings.PIN_LOCK_MINUTES минут.
    """
    if not user.has_pin:
        raise PinError("ПИН не задан. Задайте его в своём профиле.")
    now = timezone.now()
    if user.pin_locked_until and user.pin_locked_until > now:
        until = timezone.localtime(user.pin_locked_until).strftime("%H:%M")
        raise PinError(f"ПИН заблокирован из-за неверных попыток до {until}.")
    if check_password(pin, user.pin_hash):
        if user.pin_failed_attempts:
            user.pin_failed_attempts = 0
            user.save(update_fields=["pin_failed_attempts"])
        return
    user.pin_failed_attempts += 1
    left = settings.PIN_MAX_ATTEMPTS - user.pin_failed_attempts
    if left <= 0:
        user.pin_failed_attempts = 0
        user.pin_locked_until = now + timedelta(minutes=settings.PIN_LOCK_MINUTES)
        user.save(update_fields=["pin_failed_attempts", "pin_locked_until"])
        raise PinError(f"Неверный ПИН. ПИН заблокирован на {settings.PIN_LOCK_MINUTES} минут.")
    user.save(update_fields=["pin_failed_attempts"])
    raise PinError(f"Неверный ПИН. Осталось попыток: {left}.")


# --- Роли и права по модулям (ADR-013) ---------------------------------------------

# Действие в матрице «роль × модуль × действие» → стандартные права Django.
MODULE_ACTIONS: dict[str, tuple[str, ...]] = {
    "view": ("view",),
    "edit": ("add", "change"),
    "delete": ("delete",),
}


def _module_permissions(app_label: str, action: str) -> list[Permission]:
    prefixes = MODULE_ACTIONS[action]
    return [
        perm
        for perm in Permission.objects.filter(content_type__app_label=app_label)
        if perm.codename.split("_", 1)[0] in prefixes
        # История изменений — служебные модели, права на них отдельно не раздаём.
        and not perm.content_type.model.startswith("historical")
    ]


def set_module_permissions(role: Group, app_label: str, actions: set[str]) -> None:
    """Назначить роли действия в модуле целиком: {"view", "edit", "delete"}.

    Права модуля, не попавшие в actions, у роли снимаются.
    """
    unknown = actions - MODULE_ACTIONS.keys()
    if unknown:
        raise ValueError(f"Неизвестные действия: {', '.join(sorted(unknown))}")
    for action in MODULE_ACTIONS:
        perms = _module_permissions(app_label, action)
        if action in actions:
            role.permissions.add(*perms)
        else:
            role.permissions.remove(*perms)


def module_actions(role: Group, app_label: str) -> set[str]:
    """Какие действия модуля есть у роли (действие есть, если есть все его права)."""
    granted = set(role.permissions.values_list("pk", flat=True))
    result = set()
    for action in MODULE_ACTIONS:
        perms = _module_permissions(app_label, action)
        if perms and all(perm.pk in granted for perm in perms):
            result.add(action)
    return result


# --- Документы и журнал движений (ADR-004, ADR-005, ADR-012) ----------------------

next_number = numbering.next_number


def execute_document[D: Document](document: D) -> D:
    """Выполнить документ: проверки и проводки (on_execute), статус, событие.

    Всё в одной транзакции: если что-то не удалось — документ остаётся черновиком,
    и ни одна проводка не сохраняется.
    """
    with transaction.atomic():
        _lock(document)
        if document.is_deleted:
            raise DocumentError("Документ удалён.")
        if document.is_executed:
            raise DocumentError("Документ уже выполнен.")
        document.on_execute()
        document.status = Document.Status.EXECUTED
        document.executed_at = timezone.now()
        document.executed_by = get_current_user()
        _save_status(document)
        events.document_executed.send(sender=type(document), document=document)
    return document


def rollback_document[D: Document](document: D) -> D:
    """Откатить выполненный документ: обратные проводки (on_rollback), статус «черновик»."""
    with transaction.atomic():
        _lock(document)
        if not document.is_executed:
            raise DocumentError("Откатить можно только выполненный документ.")
        document.on_rollback()
        document.status = Document.Status.DRAFT
        document.executed_at = None
        document.executed_by = None
        _save_status(document)
        events.document_rolled_back.send(sender=type(document), document=document)
    return document


def _lock(document: Document) -> None:
    """Блокирует строку документа и сверяет статус: два человека не выполнят его дважды."""
    stored = type(document).all_objects.select_for_update().get(pk=document.pk)
    document.status = stored.status
    document.is_deleted = stored.is_deleted
    document._stored_status = stored.status


def _save_status(document: Document) -> None:
    document._status_change = True
    try:
        document.save(update_fields=["status", "executed_at", "executed_by"])
    finally:
        document._status_change = False


def post_entry[L: LedgerEntry](model: type[L], document: Document, **fields: Any) -> L:
    """Добавить запись в журнал движений от имени документа."""
    entry: L = model.objects.create(
        document_type=ContentType.objects.get_for_model(document),
        document_id=document.pk,
        **fields,
    )
    return entry


def entries_of[L: LedgerEntry](model: type[L], document: Document) -> QuerySet[L]:
    """Записи журнала, созданные документом (включая обратные)."""
    return model.objects.filter(
        document_type=ContentType.objects.get_for_model(document), document_id=document.pk
    )


def reverse_entries[L: LedgerEntry](model: type[L], document: Document) -> list[L]:
    """Сторнировать действующие записи документа: каждая получает обратную запись.

    Дата обратной записи — момент отката, поэтому отчёты «на дату» до отката
    по-прежнему показывают исходное движение.
    """
    active = entries_of(model, document).filter(reversal_of__isnull=True, reversed_by__isnull=True)
    reversals = []
    for entry in active:
        copy = {
            field.name: getattr(entry, field.name)
            for field in model._meta.concrete_fields
            if field.name not in _LEDGER_SERVICE_FIELDS
        }
        for name in model.amount_fields:
            copy[name] = -copy[name]
        reversals.append(model.objects.create(**copy, reversal_of=entry, posted_at=timezone.now()))
    return reversals


_LEDGER_SERVICE_FIELDS = {"id", "created_at", "created_by", "node_id", "posted_at", "reversal_of"}


# --- Печатные формы ----------------------------------------------------------------


def common_print_context(user: User | None = None) -> dict[str, Any]:
    """Переменные, доступные в любой печатной форме: clinic, user, today, now."""
    user = user or get_current_user()
    clinic = current_clinic()
    now = timezone.localtime()
    return {
        "clinic": {"name": clinic.name, "address": clinic.address, "phone": clinic.phone},
        "user": {
            "full_name": user.full_name if user else "",
            "short_name": user.short_name if user else "",
        },
        "today": now.date(),
        "now": now,
    }


def validate_print_template(kind: str, body: str) -> None:
    """Проверить шаблон на примере данных вида. Ошибка — PrintTemplateError."""
    printing.validate(body, kind, common_print_context())


def render_print(template: PrintTemplate, context: dict[str, Any]) -> bytes:
    """Напечатать: шаблон + данные документа (+ общие переменные) → PDF."""
    return printing.render_pdf(template.body, {**common_print_context(), **context})


def render_print_sample(template: PrintTemplate, as_pdf: bool = True) -> bytes | str:
    """Предпросмотр шаблона на примере данных его вида."""
    context = {**common_print_context(), **printing.get_kind(template.kind).sample()}
    if as_pdf:
        return printing.render_pdf(template.body, context)
    return printing.render_html(template.body, context)
