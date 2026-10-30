"""Медкарта: модели данных.

Таблицы модуля — его личное дело: другие модули в них не пишут (PROJECT_PLAN, 4.3).
Запись медкарты привязана к питомцу и уходит с ним к новому владельцу; клиент в записи —
владелец на момент приёма (история не меняется при смене владельца).
"""

from django.conf import settings
from django.db import models

from core.fields import QuantityField
from core.models import BaseModel, ClinicScopedModel, Directory


class Diagnosis(Directory):
    code = models.CharField("код", max_length=20, blank=True)

    class Meta(Directory.Meta):
        verbose_name = "диагноз"
        verbose_name_plural = "диагнозы"


class VisitResult(Directory):
    """Результат посещения: выздоровление, улучшение, повторный приём…"""

    class Meta(Directory.Meta):
        verbose_name = "результат посещения"
        verbose_name_plural = "результаты посещения"


class Visit(ClinicScopedModel):
    """Запись медкарты (приём)."""

    pet = models.ForeignKey(
        "clients.Pet", verbose_name="питомец", on_delete=models.PROTECT, related_name="+"
    )
    client = models.ForeignKey(
        "clients.Client", verbose_name="владелец", on_delete=models.PROTECT, related_name="+"
    )
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="врач", on_delete=models.PROTECT, related_name="+"
    )
    date = models.DateTimeField("дата и время", db_index=True)
    purpose = models.ForeignKey(
        "scheduling.VisitPurpose", verbose_name="цель обращения", on_delete=models.PROTECT,
        related_name="+",
    )  # fmt: skip
    result = models.ForeignKey(
        VisitResult, verbose_name="результат", on_delete=models.PROTECT, null=True, blank=True
    )
    appointment = models.ForeignKey(
        "scheduling.Appointment", verbose_name="приём-основание", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )  # fmt: skip
    weight = models.DecimalField("вес, кг", max_digits=7, decimal_places=3, null=True, blank=True)
    temperature = models.DecimalField(
        "температура, °C", max_digits=4, decimal_places=1, null=True, blank=True
    )
    treatment_html = models.TextField("описание лечения", blank=True)
    recommendations_html = models.TextField("рекомендации и назначения", blank=True)
    next_visit_date = models.DateField("дата повторного приёма", null=True, blank=True)

    class Meta:
        verbose_name = "запись медкарты"
        verbose_name_plural = "медкарта"
        ordering = ["-date"]

    def __str__(self) -> str:
        return f"{self.date:%d.%m.%Y} — {self.pet}"


class VisitDiagnosis(models.Model):
    class Kind(models.TextChoices):
        PRELIMINARY = "preliminary", "предварительный"
        FINAL = "final", "окончательный"

    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="diagnoses")
    diagnosis = models.ForeignKey(Diagnosis, on_delete=models.PROTECT)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.PRELIMINARY)

    class Meta:
        default_permissions = ()  # часть записи медкарты
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.diagnosis} ({self.get_kind_display()})"


class VisitItem(models.Model):
    """Позиция прайса, отмеченная в тексте медкарты через «@» — потом одной кнопкой в счёт."""

    class Section(models.TextChoices):
        TREATMENT = "treatment", "описание лечения"
        RECOMMENDATIONS = "recommendations", "рекомендации"

    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="items")
    item_unit = models.ForeignKey("catalog.ItemUnit", on_delete=models.PROTECT, related_name="+")
    quantity = QuantityField(default=1)
    section = models.CharField(max_length=16, choices=Section.choices)

    class Meta:
        default_permissions = ()  # часть записи медкарты
        ordering = ["section", "id"]

    def __str__(self) -> str:
        return f"{self.item_unit} × {self.quantity}"


class PreventionType(Directory):
    """Вид профилактики: вакцинация, дегельминтизация, обработка от эктопаразитов,
    стерилизация / кастрация, чипирование… Клиника может добавить свои.

    kind — как система ведёт себя с видом (коды совпадают с видами профилактики
    в каталоге): по нему подбираются препараты и делаются отметки в карточке питомца.
    """

    class Kind(models.TextChoices):
        VACCINATION = "vaccination", "вакцинация"
        DEWORMING = "deworming", "дегельминтизация"
        ECTOPARASITES = "ectoparasites", "обработка от эктопаразитов"
        STERILIZATION = "sterilization", "стерилизация / кастрация"
        CHIPPING = "chipping", "чипирование"
        OTHER = "other", "другое"

    kind = models.CharField("поведение", max_length=16, choices=Kind.choices, default=Kind.OTHER)
    repeat_days = models.PositiveIntegerField(
        "повтор через, дней", null=True, blank=True, help_text="Пусто — процедура однократная"
    )
    item_required = models.BooleanField(
        "препарат обязателен", default=False,
        help_text="Без препарата процедуру не записать — важно для отчётов",
    )  # fmt: skip

    class Meta(Directory.Meta):
        verbose_name = "вид профилактики"
        verbose_name_plural = "виды профилактики"

    @property
    def is_one_time(self) -> bool:
        return self.repeat_days is None


class Prevention(BaseModel):
    """Профилактическая процедура: вакцинация, дегельминтизация, обработка, стерилизация…

    Редактируется только из записи медкарты, где создана. Напоминание о повторе —
    по next_date; новая процедура того же вида (у вакцинации — той же вакциной)
    закрывает действующие напоминания.
    """

    class Stage(models.TextChoices):
        PRIMARY = "primary", "первичная"
        SECONDARY = "secondary", "повторная"

    class Reminder(models.TextChoices):
        ACTIVE = "active", "ждёт"
        CLOSED = "closed", "закрыто"

    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="preventions")
    pet = models.ForeignKey("clients.Pet", on_delete=models.PROTECT, related_name="+")
    type = models.ForeignKey(PreventionType, verbose_name="вид", on_delete=models.PROTECT)
    item = models.ForeignKey(
        "catalog.Item", verbose_name="препарат или услуга", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )  # fmt: skip
    quantity = QuantityField("количество", default=1)
    date = models.DateField("дата")
    stage = models.CharField("этап", max_length=10, choices=Stage.choices, blank=True)
    next_date = models.DateField("следующая", null=True, blank=True)
    reminder = models.CharField(max_length=8, choices=Reminder.choices, default=Reminder.ACTIVE)
    # Партия со склада: серия и срок подставляются сами. Без склада — текстом в batch_note.
    batch = models.ForeignKey(
        "inventory.Batch", verbose_name="партия", on_delete=models.PROTECT, null=True, blank=True,
        related_name="+",
    )  # fmt: skip
    batch_note = models.CharField("серия, срок годности", max_length=100, blank=True)
    note = models.CharField("примечание", max_length=255, blank=True)

    class Meta:
        verbose_name = "профилактическая процедура"
        verbose_name_plural = "профилактика"
        ordering = ["-date", "-created_at"]

    def __str__(self) -> str:
        return f"{self.type}: {self.item or ''} — {self.date:%d.%m.%Y}"
