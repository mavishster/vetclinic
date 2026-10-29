"""Клиенты и питомцы: публичный вход модуля.

Отвечает за: клиентов, питомцев, смену владельца, договоры, поиск дублей, баланс клиента.

Другие модули обращаются к модулю только через функции этого файла.
Бизнес-правила живут здесь, а не в моделях и не в API (ENGINEERING.md).
"""

import re
from typing import Any, TypedDict

from django.contrib.postgres.search import TrigramSimilarity
from django.db import transaction
from django.db.models import Q, QuerySet, Value
from django.db.models.functions import Concat

from clients.models import Client, ClientPhone, phone_search_key

# Насколько похожими должны быть ФИО, чтобы считаться возможным дублем (0…1).
NAME_SIMILARITY = 0.5


class ClientError(Exception):
    """Ошибка в данных клиента. Текст — для пользователя."""


# --- Телефоны ----------------------------------------------------------------------


def validate_phone(number: str) -> str:
    number = number.strip()
    digits = re.sub(r"\D", "", number)
    if not 5 <= len(digits) <= 15:
        raise ClientError(f"Проверьте номер телефона: «{number}».")
    return number


class PhoneData(TypedDict, total=False):
    kind: str
    number: str
    is_primary: bool
    comment: str


def _replace_phones(client: Client, phones: list[PhoneData]) -> None:
    """Заменить телефоны клиента. Основной — отмеченный, иначе первый."""
    client.phones.all().delete()
    if phones and not any(p.get("is_primary") for p in phones):
        phones = [{**phones[0], "is_primary": True}, *phones[1:]]
    seen_primary = False
    for phone in phones:
        number = validate_phone(phone["number"])
        is_primary = bool(phone.get("is_primary")) and not seen_primary
        seen_primary = seen_primary or is_primary
        ClientPhone.objects.create(
            client=client,
            kind=phone.get("kind") or ClientPhone.Kind.MOBILE,
            number=number,
            is_primary=is_primary,
            comment=phone.get("comment", ""),
        )


# --- Карточка клиента --------------------------------------------------------------


@transaction.atomic
def save_client(client: Client, phones: list[PhoneData] | None = None) -> Client:
    """Сохранить карточку клиента вместе с телефонами (если переданы)."""
    client.last_name = client.last_name.strip()
    if not client.last_name:
        raise ClientError("Укажите фамилию.")
    if client.street is not None and client.street.city_id != client.city_id:
        raise ClientError("Улица не относится к выбранному городу.")
    client.save()
    if phones is not None:
        _replace_phones(client, phones)
    return client


def set_status(client: Client, status: str) -> Client:
    """Активировать, деактивировать или сделать временным клиента."""
    if status not in Client.Status.values:
        raise ClientError(f"Неизвестный статус: {status}")
    client.status = status
    client.save(update_fields=["status"])
    return client


# --- Поиск -------------------------------------------------------------------------


def search_clients(queryset: QuerySet[Client], text: str) -> QuerySet[Client]:
    """Быстрый поиск: каждое слово ищется в ФИО; цифры — ещё и в телефонах,
    номере по журналу и дисконтной карте. «иван 345» найдёт Иванова с телефоном …345…"""
    for word in text.split():
        condition = (
            Q(last_name__icontains=word)
            | Q(first_name__icontains=word)
            | Q(middle_name__icontains=word)
            | Q(journal_number__iexact=word)
            | Q(discount_card__iexact=word)
        )
        digits = re.sub(r"\D", "", word)
        if len(digits) >= 3:
            condition |= Q(phones__search_key__contains=digits[-10:])
        queryset = queryset.filter(condition)
    return queryset.distinct()


class Duplicate(TypedDict):
    id: str
    full_name: str
    phones: list[str]
    city: str
    status: str
    reasons: list[str]  # "phone" — совпал телефон, "name" — похожее ФИО


def find_duplicates(
    last_name: str = "",
    first_name: str = "",
    middle_name: str = "",
    phones: list[str] | None = None,
    exclude_id: Any = None,
    limit: int = 10,
) -> list[Duplicate]:
    """Возможные дубли клиента: совпадающий телефон или похожее ФИО.

    Показываются и неактивные клиенты — их лучше восстановить, чем завести заново.
    """
    reasons: dict[Any, set[str]] = {}

    keys = [key for key in (phone_search_key(p) for p in phones or []) if len(key) >= 5]
    if keys:
        by_phone = Client.objects.filter(phones__search_key__in=keys).values_list("pk", flat=True)
        for pk in by_phone:
            reasons.setdefault(pk, set()).add("phone")

    full_name = " ".join(p.strip() for p in (last_name, first_name, middle_name) if p.strip())
    if len(last_name.strip()) >= 2:
        db_name = Concat("last_name", Value(" "), "first_name", Value(" "), "middle_name")
        similar = (
            Client.objects.annotate(similarity=TrigramSimilarity(db_name, full_name))
            .filter(similarity__gte=NAME_SIMILARITY)
            .order_by("-similarity")
            .values_list("pk", flat=True)[: limit * 2]
        )
        for pk in similar:
            reasons.setdefault(pk, set()).add("name")

    reasons.pop(exclude_id, None)
    if exclude_id is not None:
        reasons = {pk: r for pk, r in reasons.items() if str(pk) != str(exclude_id)}
    clients = (
        Client.objects.filter(pk__in=reasons).select_related("city").prefetch_related("phones")
    )
    found: list[Duplicate] = [
        {
            "id": str(client.pk),
            "full_name": client.full_name,
            "phones": [phone.number for phone in client.phones.all()],
            "city": client.city.name if client.city else "",
            "status": client.status,
            "reasons": sorted(reasons[client.pk]),
        }
        for client in clients
    ]
    # Сначала совпавшие по телефону — это почти наверняка тот же человек.
    found.sort(key=lambda d: ("phone" not in d["reasons"], d["full_name"]))
    return found[:limit]
