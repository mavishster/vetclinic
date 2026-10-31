"""Ядро: модели данных.

Таблицы модуля — его личное дело: другие модули в них не пишут (PROJECT_PLAN, 4.3).
Базовая модель (BaseModel) — общая механика для всех модулей (DRY, ADR-002, ADR-003).
"""

import uuid
from typing import Any, TypeVar

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.contenttypes.fields import GenericForeignKey
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from simple_history.models import HistoricalRecords

from core.context import get_current_user


def _history_user(**kwargs: Any) -> Any:
    """Кто сделал изменение — для журнала аудита (тот же источник, что и updated_by)."""
    return get_current_user()


class User(AbstractUser):
    """Учётная запись сотрудника: вход в систему, ФИО, права (ADR-022).

    Должность, график и склад по умолчанию живут в модуле staff, а не здесь:
    ядро не должно знать о модулях верхних уровней.

    Исключение из BaseModel: пользователя не удаляют и не помечают удалённым,
    а деактивируют стандартным полем is_active — так устроена авторизация Django.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    middle_name = models.CharField("отчество", max_length=150, blank=True)
    updated_at = models.DateTimeField("изменён", auto_now=True)
    version = models.PositiveIntegerField("версия", default=1, editable=False)
    # Личное оформление интерфейса: тема и основной цвет — у каждого своё, на любом компьютере.
    ui_settings = models.JSONField("оформление интерфейса", default=dict, blank=True)

    # ПИН для подтверждения операций (ADR-014). Хранится только хеш.
    pin_hash = models.CharField("ПИН (хеш)", max_length=128, blank=True, editable=False)
    pin_failed_attempts = models.PositiveSmallIntegerField(default=0, editable=False)
    pin_locked_until = models.DateTimeField(null=True, blank=True, editable=False)

    history = HistoricalRecords(
        get_user=_history_user,
        excluded_fields=[
            "password",
            "last_login",
            "pin_hash",
            "pin_failed_attempts",
            "pin_locked_until",
        ],
    )

    class Meta:
        verbose_name = "пользователь"
        verbose_name_plural = "пользователи"
        ordering = ["last_name", "first_name"]

    def __str__(self) -> str:
        return self.short_name or self.username

    @property
    def has_pin(self) -> bool:
        return bool(self.pin_hash)

    @property
    def full_name(self) -> str:
        """Иванов Иван Иванович."""
        return " ".join(p for p in (self.last_name, self.first_name, self.middle_name) if p)

    @property
    def short_name(self) -> str:
        """Иванов И. И."""
        initials = " ".join(f"{p[0]}." for p in (self.first_name, self.middle_name) if p)
        return f"{self.last_name} {initials}".strip() if self.last_name else ""

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            self.version += 1
        super().save(*args, **kwargs)


_M = TypeVar("_M", bound=models.Model)


class SoftDeleteQuerySet(models.QuerySet[_M]):
    """Удаление набора записей — тоже мягкое: записи только помечаются (ADR-003).

    Удаляем по одной через save(): так растёт версия, пишется «кто изменил»
    и запись попадает в журнал аудита. Для объёмов клиники это не медленно.
    """

    def delete(self) -> tuple[int, dict[str, int]]:
        count = 0
        for record in self:
            record.delete()
            count += 1
        return count, {self.model._meta.label: count}


class ActiveManager(models.Manager[_M]):
    """Менеджер по умолчанию: удалённые записи не видны."""

    def get_queryset(self) -> SoftDeleteQuerySet[_M]:
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=False)


class BaseModel(models.Model):
    """Основа всех моделей проекта (ADR-002, ADR-003).

    - id — UUID: записи с разных узлов не конфликтуют при синхронизации;
    - created_*/updated_* — кто и когда создал и изменил (заполняется автоматически);
    - version — растёт при каждом сохранении, нужна синхронизации;
    - node_id — на каком узле создана запись;
    - is_deleted — мягкое удаление: физически ничего не удаляется.

    objects — только неудалённые записи, all_objects — все.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField("создано", auto_now_add=True)
    updated_at = models.DateTimeField("изменено", auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="создал",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="изменил",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
    )
    version = models.PositiveIntegerField("версия", default=1, editable=False)
    node_id = models.CharField("узел", max_length=16, default="", editable=False)
    is_deleted = models.BooleanField("удалено", default=False, db_index=True, editable=False)

    history = HistoricalRecords(inherit=True, get_user=_history_user)

    objects = ActiveManager()
    all_objects = models.Manager()  # noqa: DJ012 — порядок важен: первый менеджер — по умолчанию

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        user = get_current_user()
        if self._state.adding:
            self.node_id = self.node_id or settings.NODE_ID
            self.created_by = self.created_by or user
        else:
            self.version += 1
        if user is not None:
            self.updated_by = user
        if kwargs.get("update_fields") is not None:
            service_fields = {"version", "updated_at", "updated_by"}
            kwargs["update_fields"] = {*kwargs["update_fields"], *service_fields}
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Мягкое удаление: запись помечается и пропадает из обычных выборок."""
        self.is_deleted = True
        self.save(update_fields=["is_deleted"])
        return 1, {self._meta.label: 1}

    def restore(self) -> None:
        """Восстановить мягко удалённую запись."""
        self.is_deleted = False
        self.save(update_fields=["is_deleted"])


class Clinic(BaseModel):
    """Клиника (филиал). В первой версии — одна, создаётся миграцией."""

    name = models.CharField("название", max_length=200)
    address = models.CharField("адрес", max_length=300, blank=True)
    phone = models.CharField("телефон", max_length=50, blank=True)

    class Meta:
        verbose_name = "клиника"
        verbose_name_plural = "клиники"

    def __str__(self) -> str:
        return self.name


def default_clinic_id() -> uuid.UUID | None:
    """Клиника по умолчанию для новых записей (в первой версии клиника одна)."""
    clinic = Clinic.objects.order_by("created_at").only("id").first()
    return clinic.id if clinic else None


class ClinicScopedModel(BaseModel):
    """Запись, принадлежащая клинике (филиалу): клиенты, документы… (ADR-002).

    В первой версии клиника одна и подставляется сама. Когда появится второй филиал,
    по этому полю будут разделяться данные — без переделки таблиц.
    """

    clinic = models.ForeignKey(
        Clinic,
        verbose_name="клиника",
        on_delete=models.PROTECT,
        default=default_clinic_id,
        related_name="+",
        editable=False,
    )

    class Meta:
        abstract = True


class Directory(BaseModel):
    """Справочник: виды животных, породы, цели обращения, города… (DRY, PROJECT_PLAN 3.2).

    - is_active=False — запись больше не предлагается для выбора, но остаётся
      в старых документах и карточках («деактивировать»);
    - delete() — мягкое удаление ошибочной записи (ADR-003);
    - название уникально без учёта регистра среди неудалённых записей.

    Если уникальность нужна в пределах другого поля (порода — в пределах вида),
    модель задаёт unique_within и своё ограничение в Meta.constraints.
    """

    unique_within: tuple[str, ...] = ()

    name = models.CharField("название", max_length=200)
    is_active = models.BooleanField("активна", default=True, db_index=True)

    class Meta:
        abstract = True
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                condition=models.Q(is_deleted=False),
                name="%(app_label)s_%(class)s_unique_name",
            )
        ]

    def __str__(self) -> str:
        return self.name


# --- Нумерация документов (ADR-012) -----------------------------------------------


class DocumentCounter(models.Model):
    """Счётчик номеров по типу документа на узле.

    Служебная таблица узла: не наследует BaseModel и не синхронизируется —
    у каждого узла свои счётчики, а префикс узла в номере исключает совпадения.
    """

    doc_type = models.CharField(max_length=50)
    node_id = models.CharField(max_length=16)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        default_permissions = ()  # служебная таблица: в таблице прав не показывается
        constraints = [
            models.UniqueConstraint(fields=["doc_type", "node_id"], name="core_counter_unique")
        ]

    def __str__(self) -> str:
        return f"{self.doc_type}@{self.node_id}: {self.last_number}"


# --- Базовый документ (ADR-005) ---------------------------------------------------


class DocumentError(Exception):
    """Операция с документом невозможна. Текст — для пользователя."""


class Document(BaseModel):
    """Основа документов: счёт, приход, расход, перемещение, инвентаризация, кассовые…

    Жизненный цикл: черновик → выполнен → (откат) → черновик.
    Выполненный документ не изменяется и не удаляется (ADR-005).
    Выполнение и откат — только через core.services.execute_document / rollback_document.

    Подкласс задаёт doc_type (для нумерации) и при необходимости переопределяет
    on_execute() / on_rollback() — что сделать при выполнении и откате (проводки,
    проверки). Ошибка в них отменяет операцию целиком.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "черновик"
        EXECUTED = "executed", "выполнен"

    doc_type: str = ""
    # Статус, прочитанный из базы, и разрешение сменить статус (только из сервисов ядра).
    # Поля, которые можно менять в выполненном документе без отката (не влияют на деньги
    # и остатки). Пусто — менять нельзя ничего.
    mutable_after_execution: tuple[str, ...] = ()
    _stored_status: str | None = None
    _status_change: bool = False

    number = models.CharField("номер", max_length=32, editable=False)
    date = models.DateTimeField("дата", default=timezone.now, db_index=True)
    status = models.CharField(
        "статус", max_length=16, choices=Status.choices, default=Status.DRAFT, editable=False
    )
    executed_at = models.DateTimeField("выполнен", null=True, blank=True, editable=False)
    executed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="выполнил",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
    )
    comment = models.TextField("комментарий", blank=True)

    class Meta:
        abstract = True
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(fields=["number"], name="%(app_label)s_%(class)s_unique_number")
        ]

    def __str__(self) -> str:
        return f"№ {self.number}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self._state.adding and not self.number:
            from core.numbering import next_number

            self.number = next_number(self.doc_type)
        if self._stored_status == self.Status.EXECUTED and not self._status_change:
            # Без отката можно менять только «нефинансовые» поля, перечисленные документом
            # (например, врача в счёте), и только явным update_fields — изменение пишется в аудит.
            changed = set(kwargs.get("update_fields") or [])
            if not changed or not changed <= set(self.mutable_after_execution):
                raise DocumentError("Выполненный документ нельзя изменить. Сначала сделайте откат.")
        super().save(*args, **kwargs)
        self._stored_status = self.status

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        if self.is_executed:
            raise DocumentError("Выполненный документ нельзя удалить. Сначала сделайте откат.")
        return super().delete(*args, **kwargs)

    @classmethod
    def from_db(cls, db: Any, field_names: Any, values: Any) -> "Document":
        instance = super().from_db(db, field_names, values)
        instance._stored_status = instance.__dict__.get("status")
        return instance

    @property
    def is_executed(self) -> bool:
        return self.status == self.Status.EXECUTED

    def on_execute(self) -> None:
        """Что сделать при выполнении (проводки, проверки). По умолчанию — ничего."""

    def on_rollback(self) -> None:
        """Что сделать при откате (обратные проводки, проверки). По умолчанию — ничего."""


# --- Журнал движений (ADR-004) ----------------------------------------------------


class LedgerError(Exception):
    """Попытка изменить или удалить запись журнала."""


class LedgerQuerySet(models.QuerySet[_M]):
    def delete(self) -> tuple[int, dict[str, int]]:
        raise LedgerError("Записи журнала не удаляются: исправление — обратной записью.")


class LedgerEntry(models.Model):
    """Основа журналов движений: склад, касса, баланс клиента, долги поставщикам.

    В журнал записи только добавляются (ADR-004). Остаток = сумма записей.
    Исправление — обратной записью (reversal_of), а не правкой.

    Подкласс добавляет свои измерения (товар, склад, касса, клиент…) и суммы,
    а в amount_fields перечисляет поля, которые меняют знак в обратной записи.
    """

    amount_fields: tuple[str, ...] = ()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField("записано", auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="записал",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
    )
    node_id = models.CharField("узел", max_length=16, default="", editable=False)
    posted_at = models.DateTimeField("дата движения", default=timezone.now, db_index=True)
    document_type = models.ForeignKey(
        "contenttypes.ContentType", on_delete=models.PROTECT, related_name="+"
    )
    document_id = models.UUIDField()
    document = GenericForeignKey("document_type", "document_id")
    reversal_of = models.OneToOneField(
        "self",
        verbose_name="отменяет запись",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reversed_by",
    )

    objects = LedgerQuerySet.as_manager()

    class Meta:
        abstract = True
        ordering = ["posted_at", "created_at"]
        indexes = [models.Index(fields=["document_type", "document_id"])]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise LedgerError("Записи журнала не изменяются: исправление — обратной записью.")
        self.node_id = self.node_id or settings.NODE_ID
        self.created_by = self.created_by or get_current_user()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise LedgerError("Записи журнала не удаляются: исправление — обратной записью.")


# --- Печатные формы ---------------------------------------------------------------


class PrintTemplate(Directory):
    """Шаблон печатной формы: HTML с переменными {{ ... }} (core.printing).

    Вид (kind) определяет, какие данные доступны: «счёт», «медкарта», «договор»…
    Название уникально в пределах вида.
    """

    unique_within = ("kind",)

    kind = models.CharField("вид", max_length=50)
    body = models.TextField("шаблон (HTML)")

    class Meta(Directory.Meta):
        verbose_name = "печатная форма"
        verbose_name_plural = "печатные формы"
        ordering = ["kind", "name"]
        constraints = [
            models.UniqueConstraint(
                "kind",
                Lower("name"),
                condition=models.Q(is_deleted=False),
                name="core_printtemplate_unique_name_in_kind",
            )
        ]

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        from core import services
        from core.printing import PrintTemplateError

        try:
            services.validate_print_template(self.kind, self.body)
        except PrintTemplateError as error:
            raise ValidationError({"body": str(error)}) from error


# --- Файлы -------------------------------------------------------------------------


class FileCategory(Directory):
    """Категория файла: общий, договор, анализы, рентген, УЗИ…"""

    class Meta(Directory.Meta):
        verbose_name = "категория файлов"
        verbose_name_plural = "категории файлов"


def attachment_path(instance: "Attachment", filename: str) -> str:
    """Файлы раскладываются по месяцам, а имя на диске — случайное (UUID записи).

    Настоящее имя хранится в поле name: так не бывает конфликтов и проблем
    с русскими буквами и пробелами в именах файлов.
    """
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    now = timezone.now()
    return f"attachments/{now:%Y/%m}/{instance.id}.{suffix}"


class Attachment(ClinicScopedModel):
    """Файл, прикреплённый к записи: клиенту, питомцу, позже — приёму.

    Владелец задаётся парой «тип записи + id», чтобы ядро не зависело от модулей.
    Какие записи можно снабжать файлами, модули регистрируют сами (core.attachments).
    Файлы отдаются только через API с проверкой прав — по прямой ссылке их не открыть.
    """

    owner_type = models.ForeignKey(
        "contenttypes.ContentType", on_delete=models.PROTECT, related_name="+"
    )
    owner_id = models.UUIDField(db_index=True)
    file = models.FileField("файл", upload_to=attachment_path, max_length=255)
    name = models.CharField("название", max_length=255)
    category = models.ForeignKey(
        FileCategory, verbose_name="категория", on_delete=models.PROTECT, null=True, blank=True
    )
    size = models.PositiveBigIntegerField("размер, байт", default=0)
    content_type = models.CharField("тип содержимого", max_length=100, blank=True)

    class Meta:
        verbose_name = "файл"
        verbose_name_plural = "файлы"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["owner_type", "owner_id"])]

    def __str__(self) -> str:
        return self.name


# --- Контрагенты -------------------------------------------------------------------


class Counterparty(Directory):
    """Контрагент: поставщик, лаборатория, арендодатель… Общий для склада и кассы.

    «Где показывать» — в каких документах контрагент предлагается для выбора,
    чтобы в приходе не мешались, например, арендодатель и коммунальщики.
    """

    class PersonType(models.TextChoices):
        LEGAL = "legal", "юридическое лицо"
        INDIVIDUAL = "individual", "физическое лицо"

    person_type = models.CharField(
        "лицо", max_length=10, choices=PersonType.choices, default=PersonType.LEGAL
    )
    contact = models.CharField("контактное лицо", max_length=200, blank=True)
    city = models.CharField("город", max_length=100, blank=True)
    address = models.CharField("адрес", max_length=300, blank=True)
    phone = models.CharField("телефон", max_length=50, blank=True)
    email = models.EmailField("email", blank=True)
    inn = models.CharField("ИНН", max_length=12, blank=True)
    kpp = models.CharField("КПП", max_length=9, blank=True)
    bik = models.CharField("БИК", max_length=9, blank=True)
    correspondent_account = models.CharField("корр. счёт", max_length=20, blank=True)
    settlement_account = models.CharField("расчётный счёт", max_length=20, blank=True)
    bank_name = models.CharField("банк", max_length=200, blank=True)
    note = models.TextField("примечание", blank=True)
    for_receipts = models.BooleanField("в приходных накладных", default=True)
    for_write_offs = models.BooleanField("в расходных накладных", default=True)
    for_cash = models.BooleanField("в кассовых документах", default=True)

    class Meta(Directory.Meta):
        verbose_name = "контрагент"
        verbose_name_plural = "контрагенты"

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        from core.services import counterparty_errors

        errors = counterparty_errors(self)
        if errors:
            raise ValidationError(errors)
