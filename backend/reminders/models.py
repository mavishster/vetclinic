"""Напоминания клиентам: модели данных.

Напоминание собирается само из других модулей (профилактика, записи, повторные приёмы)
и живёт, пока по нему не позвонили, клиент не записался или повод не исчез.
"""

from django.conf import settings
from django.db import models

from core.models import BaseModel


class Reminder(BaseModel):
    class Kind(models.TextChoices):
        PREVENTION = "prevention", "профилактика"
        APPOINTMENT = "appointment", "запись на приём"
        REVISIT = "revisit", "повторный приём"

    class Status(models.TextChoices):
        OPEN = "open", "к обзвону"
        NO_ANSWER = "no_answer", "не дозвонились"
        DONE = "done", "напомнили"
        BOOKED = "booked", "записался"
        DECLINED = "declined", "отказ"
        OBSOLETE = "obsolete", "уже не нужно"

    kind = models.CharField("повод", max_length=12, choices=Kind.choices)
    # Что породило напоминание (процедура, запись, приём) — чтобы не создать дубль
    # и закрыть напоминание само, когда повод исчезнет.
    source_id = models.UUIDField("источник")
    client = models.ForeignKey(
        "clients.Client", verbose_name="клиент", on_delete=models.CASCADE, related_name="+"
    )
    pet = models.ForeignKey(
        "clients.Pet",
        verbose_name="питомец",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    due_date = models.DateField("срок", db_index=True)
    text = models.CharField("о чём", max_length=255)
    status = models.CharField(
        "статус", max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    attempts = models.PositiveSmallIntegerField("попыток дозвониться", default=0)
    last_contact_at = models.DateTimeField("последний звонок", null=True, blank=True)
    contacted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="кто звонил",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    note = models.CharField("примечание", max_length=255, blank=True)

    class Meta:
        verbose_name = "напоминание"
        verbose_name_plural = "напоминания"
        ordering = ["due_date", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["kind", "source_id"], name="reminders_unique_source")
        ]

    def __str__(self) -> str:
        return f"{self.client}: {self.text}"
