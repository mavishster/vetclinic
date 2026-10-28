"""Ядро: модели данных.

Таблицы модуля — его личное дело: другие модули в них не пишут (PROJECT_PLAN, 4.3).
Базовая модель (BaseModel) — общая механика для всех модулей (DRY, ADR-002, ADR-003).
"""

import uuid
from typing import Any, TypeVar

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from core.context import get_current_user


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

    class Meta:
        verbose_name = "пользователь"
        verbose_name_plural = "пользователи"
        ordering = ["last_name", "first_name"]

    def __str__(self) -> str:
        return self.short_name or self.username

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


_M = TypeVar("_M", bound="BaseModel")


class SoftDeleteQuerySet(models.QuerySet[_M]):
    """Удаление набора записей — тоже мягкое: записи только помечаются (ADR-003)."""

    def delete(self) -> tuple[int, dict[str, int]]:
        count = self.update(
            is_deleted=True, version=models.F("version") + 1, updated_at=timezone.now()
        )
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
