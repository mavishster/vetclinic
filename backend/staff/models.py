"""Сотрудники: модели данных.

Таблицы модуля — его личное дело: другие модули в них не пишут (PROJECT_PLAN, 4.3).
Учётная запись (логин, ФИО, права) — core.User; здесь — сведения о сотруднике и график
(ADR-022, ADR-018).
"""

from django.conf import settings
from django.db import models

from core.models import BaseModel, Directory


class Position(Directory):
    """Должность: врач, ассистент, администратор…"""

    class Meta(Directory.Meta):
        verbose_name = "должность"
        verbose_name_plural = "должности"


class Employee(BaseModel):
    """Сотрудник: профиль к учётной записи."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="employee"
    )
    position = models.ForeignKey(
        Position, verbose_name="должность", on_delete=models.PROTECT, null=True, blank=True
    )
    phone = models.CharField("телефон", max_length=30, blank=True)
    color = models.CharField("цвет в графике", max_length=7, default="#24566a")
    in_schedule = models.BooleanField("показывать в графике", default=True)

    class Meta:
        verbose_name = "сотрудник"
        verbose_name_plural = "сотрудники"
        ordering = ["user__last_name", "user__first_name"]

    def __str__(self) -> str:
        return str(self.user)


class IntervalType(Directory):
    """Тип интервала графика: приём, дежурство — рабочие; отпуск, больничный — нет."""

    is_working = models.BooleanField("рабочее время", default=True)
    color = models.CharField("цвет", max_length=7, default="#24566a")

    class Meta(Directory.Meta):
        verbose_name = "тип интервала"
        verbose_name_plural = "типы интервалов графика"


class IntervalTemplate(Directory):
    """Шаблон времени: «Дневная 9–21», «Ночная 21–9» (конец раньше начала — через полночь)."""

    start_time = models.TimeField("начало")
    end_time = models.TimeField("конец")
    interval_type = models.ForeignKey(IntervalType, verbose_name="тип", on_delete=models.PROTECT)

    class Meta(Directory.Meta):
        verbose_name = "шаблон времени"
        verbose_name_plural = "шаблоны времени"


class WorkInterval(BaseModel):
    """Интервал графика сотрудника. Может переходить через полночь (ночная смена)
    или длиться несколько дней (отпуск). Интервалы одного сотрудника не пересекаются."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="сотрудник",
        on_delete=models.PROTECT,
        related_name="work_intervals",
    )
    start = models.DateTimeField("начало", db_index=True)
    end = models.DateTimeField("конец", db_index=True)
    interval_type = models.ForeignKey(IntervalType, verbose_name="тип", on_delete=models.PROTECT)
    comment = models.CharField("комментарий", max_length=255, blank=True)

    class Meta:
        verbose_name = "интервал графика"
        verbose_name_plural = "график работы"
        ordering = ["start"]

    def __str__(self) -> str:
        return f"{self.user}: {self.start:%d.%m %H:%M}–{self.end:%d.%m %H:%M}"
