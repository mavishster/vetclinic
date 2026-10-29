"""Календарь и приёмы: модели данных.

Таблицы модуля — его личное дело: другие модули в них не пишут (PROJECT_PLAN, 4.3).
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import ClinicScopedModel, Directory


class VisitPurpose(Directory):
    """Цель обращения: первичный, повторный, вакцинация, взятие анализа…

    kind — служебный признак: по нему система понимает, что это вакцинация или анализ,
    не опираясь на название (название клиника может поменять).
    """

    class Kind(models.TextChoices):
        GENERAL = "general", "приём"
        VACCINATION = "vaccination", "вакцинация"
        ANALYSIS = "analysis", "взятие анализа"
        CALL = "call", "звонок"
        TASK = "task", "задача"

    kind = models.CharField("вид", max_length=12, choices=Kind.choices, default=Kind.GENERAL)
    duration_minutes = models.PositiveSmallIntegerField("длительность, мин", default=30)
    color = models.CharField("цвет в календаре", max_length=7, default="#24566a")
    show_in_portal = models.BooleanField("показывать клиенту в личном кабинете", default=True)

    class Meta(Directory.Meta):
        verbose_name = "цель обращения"
        verbose_name_plural = "цели обращения"


class Appointment(ClinicScopedModel):
    """Запись на приём.

    Статусы: запланирован → пришёл (ожидает) → у врача → завершён;
    отдельно — отменён (с причиной) и не пришёл. «Просрочен» — не статус,
    а подсветка запланированной записи, время которой прошло.
    """

    class Status(models.TextChoices):
        PLANNED = "planned", "запланирован"
        WAITING = "waiting", "ожидает"
        IN_PROGRESS = "in_progress", "у врача"
        COMPLETED = "completed", "завершён"
        CANCELLED = "cancelled", "отменён"
        NO_SHOW = "no_show", "не пришёл"

    class Source(models.TextChoices):
        CALENDAR = "calendar", "календарь"
        WALK_IN = "walk_in", "без записи"
        CLIENT_CARD = "client_card", "карточка клиента"
        MEDICAL = "medical", "медкарта"
        VACCINATION = "vaccination", "повтор вакцинации"
        ONLINE = "online", "онлайн-запись"

    client = models.ForeignKey(
        "clients.Client", verbose_name="клиент", on_delete=models.PROTECT, related_name="+"
    )
    pet = models.ForeignKey(
        "clients.Pet",
        verbose_name="питомец",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    # Кличка и вид со слов — когда карточки питомца ещё нет (быстрая запись по телефону).
    pet_note = models.CharField("питомец со слов", max_length=100, blank=True)
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="врач",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    purpose = models.ForeignKey(
        VisitPurpose, verbose_name="цель", on_delete=models.PROTECT, null=True, blank=True
    )
    start = models.DateTimeField("начало", db_index=True)
    end = models.DateTimeField("конец")
    status = models.CharField(
        "статус", max_length=12, choices=Status.choices, default=Status.PLANNED, db_index=True
    )
    source = models.CharField(
        "откуда запись", max_length=12, choices=Source.choices, default=Source.CALENDAR
    )
    note = models.TextField("заметка для врача", blank=True)
    arrived_at = models.DateTimeField("пришёл", null=True, blank=True)
    started_at = models.DateTimeField("начат", null=True, blank=True)
    completed_at = models.DateTimeField("завершён", null=True, blank=True)
    cancel_reason = models.CharField("причина отмены", max_length=255, blank=True)
    parent = models.ForeignKey(
        "self",
        verbose_name="на основе записи",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "запись на приём"
        verbose_name_plural = "записи на приём"
        ordering = ["start"]

    def __str__(self) -> str:
        return f"{timezone.localtime(self.start):%d.%m %H:%M} — {self.client}"
