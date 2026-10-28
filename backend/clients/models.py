"""Клиенты и питомцы: модели данных.

Таблицы модуля — его личное дело: другие модули в них не пишут (PROJECT_PLAN, 4.3).
"""

from django.db import models
from django.db.models.functions import Lower

from core.models import Directory


class Species(Directory):
    """Вид животного: кошки, собаки, грызуны…"""

    class Meta(Directory.Meta):
        verbose_name = "вид животного"
        verbose_name_plural = "виды животных"


class Breed(Directory):
    """Порода. Название уникально в пределах вида: «Метис» может быть и у кошек, и у собак."""

    unique_within = ("species",)

    species = models.ForeignKey(
        Species, verbose_name="вид", on_delete=models.PROTECT, related_name="breeds"
    )

    class Meta(Directory.Meta):
        verbose_name = "порода"
        verbose_name_plural = "породы"
        constraints = [
            models.UniqueConstraint(
                "species",
                Lower("name"),
                condition=models.Q(is_deleted=False),
                name="clients_breed_unique_name_in_species",
            )
        ]
