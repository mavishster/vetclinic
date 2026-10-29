"""Клиенты и питомцы: модели данных.

Таблицы модуля — его личное дело: другие модули в них не пишут (PROJECT_PLAN, 4.3).
"""

import re
from typing import Any

from django.contrib.postgres.indexes import GinIndex
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower

from core.models import ClinicScopedModel, Directory

# --- Справочники -------------------------------------------------------------------


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


class City(Directory):
    class Meta(Directory.Meta):
        verbose_name = "город"
        verbose_name_plural = "города"


class Street(Directory):
    """Улица. Название уникально в пределах города."""

    unique_within = ("city",)

    city = models.ForeignKey(
        City, verbose_name="город", on_delete=models.PROTECT, related_name="streets"
    )

    class Meta(Directory.Meta):
        verbose_name = "улица"
        verbose_name_plural = "улицы"
        constraints = [
            models.UniqueConstraint(
                "city",
                Lower("name"),
                condition=models.Q(is_deleted=False),
                name="clients_street_unique_name_in_city",
            )
        ]


class ClientType(Directory):
    """Тип клиента: обычный, заводчик, приют…"""

    class Meta(Directory.Meta):
        verbose_name = "тип клиента"
        verbose_name_plural = "типы клиентов"


class ClientSource(Directory):
    """Откуда клиент узнал о клинике («как нашли»)."""

    class Meta(Directory.Meta):
        verbose_name = "источник клиента"
        verbose_name_plural = "источники клиентов («как нашли»)"


# --- Клиент ------------------------------------------------------------------------


class Client(ClinicScopedModel):
    """Клиент (владелец питомцев). Баланс появится вместе со счетами (журнал client_ledger)."""

    class Status(models.TextChoices):
        ACTIVE = "active", "активный"
        TEMPORARY = "temporary", "временный"
        INACTIVE = "inactive", "неактивный"

    last_name = models.CharField("фамилия", max_length=100)
    first_name = models.CharField("имя", max_length=100, blank=True)
    middle_name = models.CharField("отчество", max_length=100, blank=True)
    passport = models.CharField("паспорт (серия, номер)", max_length=50, blank=True)

    city = models.ForeignKey(
        City, verbose_name="город", on_delete=models.PROTECT, null=True, blank=True
    )
    street = models.ForeignKey(
        Street, verbose_name="улица", on_delete=models.PROTECT, null=True, blank=True
    )
    house = models.CharField("дом, квартира", max_length=100, blank=True)
    zip_code = models.CharField("индекс", max_length=10, blank=True)
    email = models.EmailField("email", blank=True)

    discount_percent = models.DecimalField(
        "скидка, %",
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    journal_number = models.CharField("номер по журналу", max_length=50, blank=True)
    discount_card = models.CharField("дисконтная карта", max_length=50, blank=True)
    client_type = models.ForeignKey(
        ClientType, verbose_name="тип", on_delete=models.PROTECT, null=True, blank=True
    )
    source = models.ForeignKey(
        ClientSource, verbose_name="как нашли", on_delete=models.PROTECT, null=True, blank=True
    )
    no_mailing = models.BooleanField("отказ от рассылок", default=False)
    in_blacklist = models.BooleanField("в чёрном списке", default=False)
    description = models.TextField("описание", blank=True)
    status = models.CharField(
        "статус", max_length=16, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )

    class Meta:
        verbose_name = "клиент"
        verbose_name_plural = "клиенты"
        ordering = ["last_name", "first_name", "middle_name"]
        indexes = [
            GinIndex(
                fields=["last_name"], name="clients_lastname_trgm", opclasses=["gin_trgm_ops"]
            ),
        ]

    def __str__(self) -> str:
        return self.full_name

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.last_name, self.first_name, self.middle_name) if p)


def phone_search_key(number: str) -> str:
    """Ключ для сравнения телефонов: последние 10 цифр.

    «8 (912) 345-67-89», «+7 912 345 67 89» и «9123456789» — один номер.
    Короткие (городские без кода) сравниваются целиком.
    """
    return re.sub(r"\D", "", number)[-10:]


class ClientPhone(models.Model):
    """Телефон клиента. Часть карточки клиента: права и история — как у клиента."""

    class Kind(models.TextChoices):
        MOBILE = "mobile", "мобильный"
        HOME = "home", "домашний"
        WORK = "work", "рабочий"
        OTHER = "other", "другой"

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="phones")
    kind = models.CharField("тип", max_length=10, choices=Kind.choices, default=Kind.MOBILE)
    number = models.CharField("номер", max_length=30)
    # Последние 10 цифр: «8 (912) 345-67-89» и «+7 912 3456789» — один и тот же номер.
    search_key = models.CharField(max_length=15, db_index=True, editable=False)
    is_primary = models.BooleanField("основной", default=False)
    comment = models.CharField("комментарий", max_length=100, blank=True)

    class Meta:
        default_permissions = ()  # права — как у клиента
        ordering = ["-is_primary", "id"]
        verbose_name = "телефон"
        verbose_name_plural = "телефоны"

    def __str__(self) -> str:
        return self.number

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.search_key = phone_search_key(self.number)
        super().save(*args, **kwargs)
