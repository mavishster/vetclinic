"""Стационар: модели данных.

Таблицы модуля — его личное дело: другие модули в них не пишут (PROJECT_PLAN, 4.3).
"""

from django.conf import settings
from django.db import models

from core.fields import QuantityField
from core.models import ClinicScopedModel, Directory


class Ward(Directory):
    """Палата или бокс стационара: сколько мест и какая услуга — «сутки стационара»."""

    class Kind(models.TextChoices):
        GENERAL = "general", "общая"
        INTENSIVE = "intensive", "интенсивная терапия"
        INFECTIOUS = "infectious", "инфекционный бокс"

    kind = models.CharField("тип", max_length=12, choices=Kind.choices, default=Kind.GENERAL)
    places = models.PositiveSmallIntegerField("мест", default=1)
    daily_item = models.ForeignKey(
        "catalog.Item",
        verbose_name="услуга «сутки стационара»",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta(Directory.Meta):
        verbose_name = "палата"
        verbose_name_plural = "палаты"


class Hospitalization(ClinicScopedModel):
    """Госпитализация: питомец в палате с даты поступления до выписки."""

    class Status(models.TextChoices):
        ACTIVE = "active", "в стационаре"
        DISCHARGED = "discharged", "выписан"

    pet = models.ForeignKey(
        "clients.Pet", verbose_name="питомец", on_delete=models.PROTECT, related_name="+"
    )
    client = models.ForeignKey(
        "clients.Client", verbose_name="владелец", on_delete=models.PROTECT, related_name="+"
    )
    ward = models.ForeignKey(
        Ward, verbose_name="палата", on_delete=models.PROTECT, related_name="hospitalizations"
    )
    place = models.PositiveSmallIntegerField("место", null=True, blank=True)
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="лечащий врач",
        on_delete=models.PROTECT,
        related_name="+",
    )
    visit = models.ForeignKey(
        "medical.Visit",
        verbose_name="приём-основание",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    admitted_at = models.DateTimeField("поступил")
    planned_discharge = models.DateField("плановая выписка", null=True, blank=True)
    discharged_at = models.DateTimeField("выписан", null=True, blank=True)
    reason = models.TextField("причина госпитализации, диагноз", blank=True)
    outcome = models.TextField("итог (при выписке)", blank=True)
    status = models.CharField(
        "статус", max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    invoice_id = models.UUIDField("счёт за стационар", null=True, blank=True)

    class Meta:
        verbose_name = "госпитализация"
        verbose_name_plural = "стационар"
        ordering = ["-admitted_at"]

    def __str__(self) -> str:
        return f"{self.pet} — {self.ward}"


class Route(models.TextChoices):
    ORAL = "oral", "внутрь"
    SUBCUTANEOUS = "sc", "подкожно"
    INTRAMUSCULAR = "im", "внутримышечно"
    INTRAVENOUS = "iv", "внутривенно"
    DRIP = "drip", "капельно"
    TOPICAL = "topical", "наружно"
    EYES = "eyes", "в глаза"
    EARS = "ears", "в уши"
    RECTAL = "rectal", "ректально"
    PROCEDURE = "procedure", "процедура"
    OTHER = "other", "другое"


class TreatmentPlan(models.Model):
    """Назначение в стационаре: что, сколько, как и в какие часы — на N дней.

    По назначению создаются отдельные отметки (TreatmentTask) на каждый час каждого дня —
    это и есть лист назначений, где персонал отмечает выполнение.
    """

    hospitalization = models.ForeignKey(
        Hospitalization, on_delete=models.CASCADE, related_name="plans"
    )
    item = models.ForeignKey(
        "catalog.Item",
        verbose_name="из прайса",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    title = models.CharField("препарат или процедура", max_length=255)
    dose = models.CharField("доза", max_length=100, blank=True)
    route = models.CharField("способ", max_length=10, choices=Route.choices, default=Route.ORAL)
    times = models.JSONField("часы", default=list)  # ["08:00", "20:00"]
    start_date = models.DateField("с даты")
    days = models.PositiveSmallIntegerField("дней", default=1)
    note = models.CharField("примечание", max_length=255, blank=True)
    is_active = models.BooleanField("действует", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "назначение в стационаре"
        verbose_name_plural = "назначения в стационаре"
        default_permissions = ()  # часть госпитализации
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"{self.title} {self.dose}".strip()


class TreatmentTask(models.Model):
    """Отметка в листе назначений: конкретное время, выполнено или пропущено, кем."""

    class Status(models.TextChoices):
        PLANNED = "planned", "запланировано"
        DONE = "done", "выполнено"
        SKIPPED = "skipped", "пропущено"

    plan = models.ForeignKey(TreatmentPlan, on_delete=models.CASCADE, related_name="tasks")
    hospitalization = models.ForeignKey(
        Hospitalization, on_delete=models.CASCADE, related_name="tasks"
    )
    scheduled_at = models.DateTimeField("когда", db_index=True)
    status = models.CharField(
        "статус", max_length=8, choices=Status.choices, default=Status.PLANNED
    )
    done_at = models.DateTimeField("отмечено", null=True, blank=True)
    done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="кто",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    note = models.CharField("примечание", max_length=255, blank=True)
    quantity = QuantityField("израсходовано (для счёта)", null=True, blank=True)

    class Meta:
        verbose_name = "отметка в листе назначений"
        verbose_name_plural = "отметки в листе назначений"
        default_permissions = ()  # часть госпитализации
        ordering = ["scheduled_at", "id"]

    def __str__(self) -> str:
        return f"{self.plan} — {self.scheduled_at:%d.%m %H:%M}"


class Observation(models.Model):
    """Наблюдение в стационаре: температура, вес, пульс, аппетит, заметка."""

    hospitalization = models.ForeignKey(
        Hospitalization, on_delete=models.CASCADE, related_name="observations"
    )
    at = models.DateTimeField("когда")
    temperature = models.DecimalField(
        "t, °C", max_digits=4, decimal_places=1, null=True, blank=True
    )
    weight = models.DecimalField("вес, кг", max_digits=7, decimal_places=3, null=True, blank=True)
    pulse = models.PositiveSmallIntegerField("пульс", null=True, blank=True)
    note = models.CharField("состояние, аппетит, заметка", max_length=500, blank=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="кто",
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "наблюдение"
        verbose_name_plural = "наблюдения в стационаре"
        default_permissions = ()  # часть госпитализации
        ordering = ["-at"]

    def __str__(self) -> str:
        return f"{self.hospitalization}: {self.at:%d.%m %H:%M}"
