"""Ядро: публичный вход модуля.

Отвечает за: базовые модели, документы, журнал движений, справочники, права,
аудит, нумерацию, печать.

Другие модули обращаются к модулю только через функции этого файла.
Бизнес-правила живут здесь, а не в моделях и не в API (ENGINEERING.md).
"""

import itertools
from datetime import timedelta
from typing import Any, TypedDict

from django.apps import apps
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import DatabaseError, connection, transaction
from django.db.models import QuerySet
from django.utils import timezone

from core import events, numbering, printing
from core.context import get_current_user
from core.models import (
    Clinic,
    Directory,
    Document,
    DocumentError,
    LedgerEntry,
    PrintTemplate,
    User,
)


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


# --- Роли и права: раздел → сущности → действия (ADR-013) --------------------------

# Действие в таблице прав → стандартные права Django.
MODULE_ACTIONS: dict[str, tuple[str, ...]] = {
    "view": ("view",),
    "edit": ("add", "change"),
    "delete": ("delete",),
}

# Сущности вне модулей проекта, которые показываются в таблице прав внутри раздела.
_EXTRA_ENTITIES = {"core": ["auth.group"]}
_ENTITY_TITLES = {"auth.group": "Роли и права"}
_MODULE_TITLES = {"core": "Администрирование"}


class PermissionEntity(TypedDict):
    code: str  # «приложение.модель», например «clients.species»
    title: str


class PermissionModule(TypedDict):
    code: str
    title: str
    entities: list[PermissionEntity]


def _entity_title(model: type[Any]) -> str:
    title = str(model._meta.verbose_name_plural)
    return title[:1].upper() + title[1:]


def permission_modules() -> list[PermissionModule]:
    """Строки таблицы прав: разделы и их сущности (справочники, документы…).

    Показываются модели модулей проекта, у которых есть права. Служебные модели
    без прав (default_permissions = ()) и журналы истории не показываются.
    """
    result: list[PermissionModule] = []
    for app in settings.PROJECT_APPS:
        config = apps.get_app_config(app)
        models_with_rights = [
            model
            for model in config.get_models()
            if model._meta.default_permissions
            and not model._meta.label_lower.split(".")[1].startswith("historical")
        ]
        # Сначала основные данные раздела (клиенты, документы), затем справочники.
        models_with_rights.sort(key=lambda model: issubclass(model, Directory))
        entities: list[PermissionEntity] = [
            {"code": model._meta.label_lower, "title": _entity_title(model)}
            for model in models_with_rights
        ]
        entities += [
            {"code": code, "title": _ENTITY_TITLES[code]} for code in _EXTRA_ENTITIES.get(app, [])
        ]
        if entities:
            title = _MODULE_TITLES.get(app, str(config.verbose_name))
            result.append({"code": app, "title": title, "entities": entities})
    return result


def permission_entities() -> set[str]:
    return {entity["code"] for module in permission_modules() for entity in module["entities"]}


def _entity_permissions(entity: str, action: str) -> list[Permission]:
    app_label, model = entity.split(".")
    codenames = [f"{prefix}_{model}" for prefix in MODULE_ACTIONS[action]]
    return list(
        Permission.objects.filter(content_type__app_label=app_label, codename__in=codenames)
    )


def _check(entity: str | None, actions: set[str]) -> None:
    unknown = actions - MODULE_ACTIONS.keys()
    if unknown:
        raise ValueError(f"Неизвестные действия: {', '.join(sorted(unknown))}")
    if entity is not None and entity not in permission_entities():
        raise ValueError(f"Неизвестный раздел или справочник: {entity}")


def set_entity_permissions(role: Group, entity: str, actions: set[str]) -> None:
    """Назначить роли действия над сущностью: {"view", "edit", "delete"}.

    «Редактирование» = добавление + изменение. Не попавшие в actions права снимаются.
    """
    _check(entity, actions)
    for action in MODULE_ACTIONS:
        perms = _entity_permissions(entity, action)
        if action in actions:
            role.permissions.add(*perms)
        else:
            role.permissions.remove(*perms)


def entity_actions(role: Group, entity: str) -> set[str]:
    """Какие действия над сущностью есть у роли (действие есть, если есть все его права)."""
    granted = set(role.permissions.values_list("pk", flat=True))
    return {
        action
        for action in MODULE_ACTIONS
        if (perms := _entity_permissions(entity, action))
        and all(perm.pk in granted for perm in perms)
    }


def _module_entities(module: str) -> list[str]:
    for item in permission_modules():
        if item["code"] == module:
            return [entity["code"] for entity in item["entities"]]
    raise ValueError(f"Неизвестный раздел или справочник: {module}")


def set_module_permissions(role: Group, module: str, actions: set[str]) -> None:
    """Назначить одинаковые действия всем сущностям раздела — «всё сразу»."""
    _check(None, actions)
    for entity in _module_entities(module):
        set_entity_permissions(role, entity, actions)


def module_actions(role: Group, module: str) -> set[str]:
    """Действия, которые есть у роли для всех сущностей раздела."""
    per_entity = [entity_actions(role, entity) for entity in _module_entities(module)]
    return set.intersection(*per_entity) if per_entity else set()


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


# --- Учётные записи сотрудников (ADR-022) ------------------------------------------


class UserError(Exception):
    """Ошибка в учётной записи. Текст — для пользователя."""


def _check_password(password: str, user: User) -> None:
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    try:
        validate_password(password, user)
    except ValidationError as error:
        raise UserError(" ".join(error.messages)) from error


def save_user_account(
    user: User, password: str | None = None, roles: list[Group] | None = None
) -> User:
    """Создать или изменить учётную запись сотрудника.

    password — задать или сменить пароль (у новой учётной записи обязателен).
    roles — заменить роли; права суперпользователя через этот путь не выдаются.
    """
    user.username = user.username.strip()
    if not user.username:
        raise UserError("Укажите логин.")
    if User.objects.filter(username__iexact=user.username).exclude(pk=user.pk).exists():
        raise UserError("Такой логин уже занят.")
    if not user.last_name.strip():
        raise UserError("Укажите фамилию.")
    if user._state.adding and not password:
        raise UserError("Задайте пароль.")
    if password:
        _check_password(password, user)
        user.set_password(password)
    user.save()
    if roles is not None:
        user.groups.set(roles)
    return user
