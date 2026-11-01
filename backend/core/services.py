"""Ядро: публичный вход модуля.

Отвечает за: базовые модели, документы, журнал движений, справочники, права,
аудит, нумерацию, печать.

Другие модули обращаются к модулю только через функции этого файла.
Бизнес-правила живут здесь, а не в моделях и не в API (ENGINEERING.md).
"""

import itertools
import re
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
    is_directory: bool  # справочник (списки для выбора) или рабочие данные раздела
    hint: str  # что именно разрешается — первая фраза описания модели


class SpecialPermission(TypedDict):
    code: str  # «приложение.право», например «billing.rollback_invoice»
    title: str


class PermissionModule(TypedDict):
    code: str
    title: str
    entities: list[PermissionEntity]
    special: list[SpecialPermission]  # особые права раздела: откаты, возвраты, себестоимость…


def _entity_title(model: type[Any]) -> str:
    title = str(model._meta.verbose_name_plural)
    return title[:1].upper() + title[1:]


# Пояснения к строкам таблицы прав — для того, кто настраивает роли (не для разработчика).
PERMISSION_HINTS = {
    "core.user": "Учётные записи сотрудников: логин, пароль, ФИО.",
    "core.clinic": "Реквизиты клиники — для печатных форм.",
    "core.attachment": "Файлы у клиентов, питомцев и приёмов: сканы, снимки, договоры.",
    "core.printtemplate": "Шаблоны печати: выписка из медкарты, счёт, этикетка.",
    "core.filecategory": "Список категорий файлов: договор, анализы, рентген…",
    "core.counterparty": "Поставщики и другие организации — для склада и кассы.",
    "auth.group": "Роли и их права — кто что может делать в системе.",
    "clients.client": "Карточки клиентов: контакты, адрес, скидка.",
    "clients.pet": "Карточки питомцев: вес, смена владельца, «умер».",
    "clients.clientcontract": "Договоры с клиентами.",
    "clients.clientledger": "Баланс клиента — долги и авансы (меняется счетами и кассой).",
    "clients.species": "Список видов животных.",
    "clients.breed": "Список пород.",
    "clients.color": "Список окрасов.",
    "clients.city": "Список городов.",
    "clients.street": "Список улиц.",
    "clients.clienttype": "Список типов клиентов.",
    "clients.clientsource": "Список «как нашли клинику».",
    "catalog.item": "Прайс: товары, услуги, комбинации и их цены.",
    "catalog.unit": "Список единиц измерения.",
    "catalog.itemgroup": "Группы прайса и наценки групп.",
    "staff.employee": "Сотрудники: карточки, логины, назначение ролей.",
    "staff.workinterval": "График работы сотрудников.",
    "staff.position": "Список должностей.",
    "staff.intervaltype": "Типы интервалов графика: приём, дежурство, отпуск…",
    "staff.intervaltemplate": "Шаблоны времени для графика.",
    "scheduling.appointment": "Календарь: записи на приём и их статусы.",
    "scheduling.visitpurpose": "Список целей обращения.",
    "medical.visit": "Записи медкарты: приёмы, диагнозы, лечение.",
    "medical.prevention": "Вакцинации, дегельминтизация и другая профилактика.",
    "medical.diagnosis": "Список диагнозов.",
    "medical.visitresult": "Список результатов посещения.",
    "medical.preventiontype": "Список видов профилактики.",
    "medical.texttemplate": "Шаблоны текста медкарты: общие для всех; личные врач ведёт сам.",
    "billing.invoice": "Счета клиентов: создание, выполнение, откат.",
    "inventory.stockdocument": "Приходы, расходы, перемещения, инвентаризации.",
    "inventory.batch": "Партии товаров: серии и сроки годности.",
    "inventory.stockmovement": "Остатки на складах.",
    "inventory.minstock": "Минимальные остатки — «нужно заказать».",
    "inventory.warehouse": "Список складов.",
    "inventory.manufacturer": "Список производителей.",
    "cash.cashshift": "Смены и закрытие кассы.",
    "cash.payment": "Приём оплат и их возврат.",
    "cash.cashoperation": "Внесение, выдача, перемещение денег, возврат аванса.",
    "cash.cashmovement": "Остатки в кассах и движение денег.",
    "cash.cashregister": "Список касс.",
    "reminders.reminder": "Напоминания клиентам: список для обзвона и итоги звонков.",
}


def _entity_hint(model: type[Any]) -> str:
    return PERMISSION_HINTS.get(model._meta.label_lower, "")


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
            {
                "code": model._meta.label_lower,
                "title": _entity_title(model),
                "is_directory": issubclass(model, Directory),
                "hint": _entity_hint(model),
            }
            for model in models_with_rights
        ]
        entities += [
            {
                "code": code,
                "title": _ENTITY_TITLES[code],
                "is_directory": False,
                "hint": PERMISSION_HINTS.get(code, ""),
            }
            for code in _EXTRA_ENTITIES.get(app, [])
        ]
        special: list[SpecialPermission] = [
            {"code": f"{app}.{codename}", "title": str(name)}
            for model in models_with_rights
            for codename, name in model._meta.permissions
        ]
        if entities:
            title = _MODULE_TITLES.get(app, str(config.verbose_name))
            result.append({"code": app, "title": title, "entities": entities, "special": special})
    return result


def special_permissions() -> set[str]:
    return {sp["code"] for module in permission_modules() for sp in module["special"]}


def _special(code: str) -> Permission:
    app_label, codename = code.split(".")
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


def set_special_permissions(role: Group, codes: set[str]) -> None:
    """Назначить роли особые права (остальные особые права снимаются)."""
    known = special_permissions()
    unknown = codes - known
    if unknown:
        raise ValueError(f"Неизвестные особые права: {', '.join(sorted(unknown))}")
    for code in known:
        permission = _special(code)
        if code in codes:
            role.permissions.add(permission)
        else:
            role.permissions.remove(permission)


def special_of(role: Group) -> set[str]:
    granted = {
        f"{p.content_type.app_label}.{p.codename}"
        for p in role.permissions.select_related("content_type")
    }
    return granted & special_permissions()


# Шаблоны ролей: типичные наборы прав, с которых удобно начать. «edit» = добавлять и менять.
_V, _E, _D = "view", "edit", "delete"
_DIRECTORIES_VIEW = [
    "clients.species",
    "clients.breed",
    "clients.color",
    "clients.city",
    "clients.street",
    "clients.clienttype",
    "clients.clientsource",
    "catalog.unit",
    "catalog.itemgroup",
    "scheduling.visitpurpose",
    "medical.diagnosis",
    "medical.visitresult",
    "medical.preventiontype",
    "staff.position",
    "inventory.warehouse",
    "core.filecategory",
    "cash.cashregister",
]
ROLE_TEMPLATES: list[dict[str, Any]] = [
    {
        "code": "doctor",
        "name": "Врач",
        "description": "Приём: календарь, медкарта, профилактика, счета по приёму.",
        "access": {
            **{code: [_V] for code in _DIRECTORIES_VIEW},
            "clients.client": [_V, _E],
            "clients.pet": [_V, _E],
            "clients.clientcontract": [_V],
            "clients.clientledger": [_V],
            "scheduling.appointment": [_V, _E],
            "medical.visit": [_V, _E],
            "medical.texttemplate": [_V, _E],
            "medical.prevention": [_V, _E],
            "medical.diagnosis": [_V, _E],
            "catalog.item": [_V],
            "inventory.stockmovement": [_V],
            "inventory.batch": [_V],
            "billing.invoice": [_V, _E],
            "core.attachment": [_V, _E],
            "staff.workinterval": [_V],
        },
        "special": [],
    },
    {
        "code": "registrar",
        "name": "Регистратор",
        "description": "Ресепшен: клиенты, питомцы, договоры, запись, счета, приём оплат.",
        "access": {
            **{code: [_V] for code in _DIRECTORIES_VIEW},
            "clients.client": [_V, _E],
            "clients.pet": [_V, _E],
            "clients.clientcontract": [_V, _E],
            "clients.clientledger": [_V],
            "clients.city": [_V, _E],
            "clients.street": [_V, _E],
            "clients.breed": [_V, _E],
            "clients.color": [_V, _E],
            "reminders.reminder": [_V, _E],
            "scheduling.appointment": [_V, _E, _D],
            "medical.visit": [_V],
            "medical.prevention": [_V],
            "catalog.item": [_V],
            "billing.invoice": [_V, _E],
            "cash.payment": [_V, _E],
            "cash.cashmovement": [_V],
            "core.attachment": [_V, _E],
            "staff.workinterval": [_V],
        },
        "special": [],
    },
    {
        "code": "cashier",
        "name": "Кассир",
        "description": "Касса: оплаты и их возврат, авансы, внесение и выдача, закрытие кассы.",
        "access": {
            **{code: [_V] for code in _DIRECTORIES_VIEW},
            "clients.client": [_V],
            "clients.clientledger": [_V],
            "catalog.item": [_V],
            "billing.invoice": [_V, _E],
            "cash.payment": [_V, _E],
            "cash.cashoperation": [_V, _E],
            "cash.cashmovement": [_V],
            "cash.cashshift": [_V],
            "core.counterparty": [_V],
        },
        "special": ["cash.refund_payment", "cash.return_advance", "cash.close_shift"],
    },
    {
        "code": "storekeeper",
        "name": "Кладовщик",
        "description": "Склад: приходы, расходы, инвентаризации, остатки; прайс; закупочные цены.",
        "access": {
            **{code: [_V] for code in _DIRECTORIES_VIEW},
            "catalog.item": [_V, _E],
            "catalog.unit": [_V, _E],
            "catalog.itemgroup": [_V, _E],
            "inventory.stockdocument": [_V, _E, _D],
            "inventory.batch": [_V],
            "inventory.stockmovement": [_V],
            "inventory.minstock": [_V, _E, _D],
            "inventory.warehouse": [_V, _E],
            "inventory.manufacturer": [_V, _E],
            "core.counterparty": [_V, _E],
        },
        "special": ["inventory.rollback_stockdocument", "catalog.view_cost"],
    },
    {
        "code": "manager",
        "name": "Руководитель",
        "description": "Всё: все разделы и справочники, особые права, настройка ролей.",
        "access": "all",
        "special": "all",
    },
]


def role_templates() -> list[dict[str, Any]]:
    """Шаблоны ролей, развёрнутые под текущий набор разделов (неизвестное отбрасывается)."""
    entities = permission_entities()
    specials = special_permissions()
    result = []
    for template in ROLE_TEMPLATES:
        if template["access"] == "all":
            access = {code: [_V, _E, _D] for code in entities}
        else:
            access = {c: a for c, a in template["access"].items() if c in entities}
        special = (
            sorted(specials)
            if template["special"] == "all"
            else [c for c in template["special"] if c in specials]
        )
        result.append({**template, "access": access, "special": special})
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
next_value = numbering.next_value


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


# --- Использование записей ---------------------------------------------------------


def usage_count(record: Any) -> int:
    """Сколько действующих записей ссылаются на эту (журналы истории не считаются).

    Нужен, чтобы не удалить справочник, которым пользуются: группу с товарами,
    породу у питомцев, город у клиентов.
    """
    total = 0
    for relation in record._meta.related_objects:
        model = relation.related_model
        if model._meta.model_name.startswith("historical") or not relation.field.concrete:
            continue
        manager = model._default_manager
        total += manager.filter(**{relation.field.name: record}).count()
    return total


# --- Контрагенты -------------------------------------------------------------------

# Реквизит → допустимое число цифр (пусто — не проверяем).
_REQUISITES = {
    "inn": ((10, 12), "ИНН — 10 цифр у организации или 12 у ИП и физлица."),
    "kpp": ((9,), "КПП — 9 цифр."),
    "bik": ((9,), "БИК — 9 цифр."),
    "correspondent_account": ((20,), "Корр. счёт — 20 цифр."),
    "settlement_account": ((20,), "Расчётный счёт — 20 цифр."),
}


def counterparty_errors(counterparty: Any) -> dict[str, str]:
    """Проверка реквизитов контрагента: только цифры и правильная длина."""
    errors: dict[str, str] = {}
    for field, (lengths, message) in _REQUISITES.items():
        value = (getattr(counterparty, field) or "").strip()
        setattr(counterparty, field, value)
        if value and (not value.isdigit() or len(value) not in lengths):
            errors[field] = message
    return errors


# --- Оформление интерфейса ---------------------------------------------------------

UI_THEMES = {"light", "dark", "auto"}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def save_ui_settings(user: User, changes: dict[str, Any]) -> dict[str, Any]:
    """Сохранить личное оформление: тема (светлая / тёмная / как в системе) и основной
    цвет (#RRGGBB). Неизвестные ключи игнорируются."""
    settings_ = dict(user.ui_settings or {})
    if "theme" in changes:
        if changes["theme"] not in UI_THEMES:
            raise ValueError("Тема: светлая, тёмная или как в системе.")
        settings_["theme"] = changes["theme"]
    if "primary" in changes:
        color = changes["primary"] or ""
        if color and not _HEX.match(color):
            raise ValueError("Цвет задаётся в виде #RRGGBB.")
        settings_["primary"] = color
    user.ui_settings = settings_
    user.save(update_fields=["ui_settings"])
    return settings_


# --- Резервные копии ---------------------------------------------------------------


def backup_status() -> dict[str, Any]:
    """Состояние резервных копий для главной: последняя копия, проверка восстановления,
    и «всё ли в порядке» (копия свежая и удалась, восстановление проверено)."""
    import json
    from datetime import datetime

    from django.utils import timezone

    def read(name: str) -> dict[str, Any] | None:
        path = settings.BACKUP_DIR / f"{name}.json"
        try:
            return dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return None

    if not settings.BACKUP_DIR.is_dir():
        # Папки копий нет — это компьютер разработки, а не сервер клиники.
        return {
            "configured": False,
            "backup": None,
            "restore_check": None,
            "ok": True,
            "problems": [],
        }
    backup, check = read("backup"), read("restore_check")
    problems: list[str] = []
    if backup is None:
        problems.append("Резервных копий ещё нет — проверьте, что запущен контейнер backup.")
    elif not backup.get("ok"):
        problems.append("Последняя резервная копия не удалась.")
    else:
        made = datetime.strptime(backup["at"], "%Y-%m-%dT%H:%M:%S%z")
        hours = (timezone.now() - made).total_seconds() / 3600
        if hours > settings.BACKUP_MAX_AGE_HOURS:
            problems.append(f"Последней резервной копии больше {int(hours)} ч.")
    if check is not None and not check.get("ok"):
        problems.append("Проверка восстановления из копии не прошла.")
    return {
        "configured": True,
        "backup": backup,
        "restore_check": check,
        "ok": not problems,
        "problems": problems,
    }
