"""Перенос из VetManager: что уже перенесено.

Связь «запись VetManager → запись нашей системы» нужна, чтобы повторный перенос
не задваивал данные и чтобы медкарты и счета находили своих клиентов и питомцев.
"""

import uuid

from django.db import models


class Imported(models.Model):
    kind = models.CharField("что переносили", max_length=30, db_index=True)
    external_id = models.CharField("номер в VetManager", max_length=50)
    target_id = models.UUIDField("номер у нас", default=uuid.uuid4)
    imported_at = models.DateTimeField("когда перенесли", auto_now=True)

    class Meta:
        verbose_name = "перенесённая запись"
        verbose_name_plural = "перенесённые записи"
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "external_id"], name="vetmanager_unique_external"
            )
        ]
        indexes = [models.Index(fields=["kind", "target_id"])]
        default_permissions = ()
        permissions = [("run_import", "Переносить данные из VetManager")]

    def __str__(self) -> str:
        return f"{self.kind} {self.external_id}"
