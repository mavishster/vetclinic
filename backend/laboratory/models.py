"""Лаборатория: модели данных.

Результаты анализов хранятся данными — показатель, значение, единица, референс, отметка
↑↓ — а не таблицей в тексте медкарты: так видны отклонения и динамика показателя.
"""

from django.db import models

from core.models import ClinicScopedModel, Directory


class Analyte(Directory):
    """Показатель анализа: код прибора (WBC, ALT…), русское название, единица, группа.

    Неизвестный код из прибора заводится сам — с названием из сообщения.
    """

    code = models.CharField("код прибора", max_length=50, unique=True)
    unit = models.CharField("единица", max_length=30, blank=True)
    group = models.CharField("группа", max_length=60, blank=True)  # ОАК, биохимия, ПЦР…

    class Meta(Directory.Meta):
        verbose_name = "показатель анализа"
        verbose_name_plural = "показатели анализов"


class AnalyteNorm(models.Model):
    """Норма показателя для вида животного — если прибор не прислал референс."""

    analyte = models.ForeignKey(Analyte, on_delete=models.CASCADE, related_name="norms")
    species = models.ForeignKey("clients.Species", on_delete=models.CASCADE, related_name="+")
    low = models.DecimalField("от", max_digits=12, decimal_places=4, null=True, blank=True)
    high = models.DecimalField("до", max_digits=12, decimal_places=4, null=True, blank=True)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["analyte", "species"], name="laboratory_norm_unique")
        ]

    def __str__(self) -> str:
        return f"{self.analyte} ({self.species}): {self.low}–{self.high}"


class LabResult(ClinicScopedModel):
    """Результат исследования с прибора (или внесённый вручную).

    Привязан к записи медкарты по номеру для анализатора; не нашлось — «нераспределён».
    """

    class Status(models.TextChoices):
        ASSIGNED = "assigned", "в медкарте"
        UNASSIGNED = "unassigned", "не распределён"

    visit = models.ForeignKey(
        "medical.Visit",
        verbose_name="запись медкарты",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    pet = models.ForeignKey(
        "clients.Pet",
        verbose_name="питомец",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    device = models.CharField("прибор", max_length=100)
    analysis = models.CharField("исследование", max_length=200)
    code_entered = models.CharField("номер, введённый в прибор", max_length=50, blank=True)
    received_at = models.DateTimeField("получен", db_index=True)
    status = models.CharField("статус", max_length=12, choices=Status.choices, db_index=True)
    # Отпечаток сообщения — повторная отправка того же результата прибором не задвоится.
    message_id = models.CharField("отпечаток сообщения", max_length=100, blank=True, db_index=True)

    class Meta:
        verbose_name = "результат анализа"
        verbose_name_plural = "результаты анализов"
        ordering = ["-received_at"]

    def __str__(self) -> str:
        return f"{self.analysis} — {self.received_at:%d.%m.%Y %H:%M}"


class LabValue(models.Model):
    class Flag(models.TextChoices):
        NONE = "", "—"
        NORMAL = "normal", "норма"
        LOW = "low", "ниже нормы"
        HIGH = "high", "выше нормы"
        POSITIVE = "positive", "положительно"

    result = models.ForeignKey(LabResult, on_delete=models.CASCADE, related_name="values")
    analyte = models.ForeignKey(
        Analyte, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    name = models.CharField("показатель", max_length=200)
    value = models.CharField("результат", max_length=100)
    numeric = models.DecimalField("числом", max_digits=14, decimal_places=4, null=True, blank=True)
    unit = models.CharField("единица", max_length=30, blank=True)
    reference = models.CharField("референс", max_length=60, blank=True)
    flag = models.CharField("отметка", max_length=10, choices=Flag.choices, blank=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        default_permissions = ()  # часть результата
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return f"{self.name}: {self.value} {self.unit}".strip()
