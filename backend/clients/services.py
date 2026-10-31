"""Клиенты и питомцы: публичный вход модуля.

Отвечает за: клиентов, питомцев, смену владельца, договоры, поиск дублей, баланс клиента.

Другие модули обращаются к модулю только через функции этого файла.
Бизнес-правила живут здесь, а не в моделях и не в API (ENGINEERING.md).
"""

import re
from datetime import date
from decimal import Decimal
from typing import Any, TypedDict

from django.contrib.postgres.search import TrigramSimilarity
from django.db import transaction
from django.db.models import Exists, OuterRef, Q, QuerySet, Value
from django.db.models.functions import Concat
from django.utils import timezone

from clients.models import (
    Client,
    ClientContract,
    ClientPhone,
    Pet,
    PetOwnership,
    PetWeight,
    phone_search_key,
)
from core import services as core_services

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
    """Быстрый поиск: каждое слово ищется в ФИО и кличках питомцев; цифры — ещё и в
    телефонах, номере по журналу и дисконтной карте. «иван 345» найдёт Иванова с телефоном …345…"""
    for word in text.split():
        condition = (
            Q(last_name__icontains=word)
            | Q(first_name__icontains=word)
            | Q(middle_name__icontains=word)
            | Q(journal_number__iexact=word)
            | Q(discount_card__iexact=word)
            | Q(pets__name__icontains=word)
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


# --- Питомцы -----------------------------------------------------------------------


def _today() -> date:
    return timezone.localdate()


@transaction.atomic
def save_pet(pet: Pet) -> Pet:
    """Сохранить карточку питомца. Новому питомцу открывается период владения."""
    pet.name = pet.name.strip()
    if not pet.name:
        raise ClientError("Укажите кличку.")
    if pet.breed.species_id != pet.species_id:
        raise ClientError("Порода не относится к выбранному виду.")
    if pet.birth_date and pet.birth_date > _today():
        raise ClientError("Дата рождения не может быть в будущем.")
    if pet.status == Pet.Status.DEAD:
        if pet.death_date is None:
            pet.death_date = _today()
        if pet.birth_date and pet.death_date < pet.birth_date:
            raise ClientError("Дата смерти раньше даты рождения.")
    else:
        pet.death_date = None
    is_new = pet._state.adding
    pet.save()
    if is_new:
        PetOwnership.objects.create(pet=pet, client=pet.owner, date_from=_today())
    return pet


@transaction.atomic
def transfer_pet(pet: Pet, new_owner: Client) -> Pet:
    """Передать питомца другому владельцу.

    Медкарта уходит вместе с питомцем, а счета остаются у прежнего владельца.
    У прежнего владельца питомец виден в «бывших».
    """
    if new_owner.pk == pet.owner_id:
        raise ClientError("Питомец уже принадлежит этому клиенту.")
    today = _today()
    pet.ownerships.filter(date_to__isnull=True).update(date_to=today)
    PetOwnership.objects.create(pet=pet, client=new_owner, date_from=today)
    pet.owner = new_owner
    pet.save(update_fields=["owner"])
    return pet


def mark_dead(pet: Pet, death_date: date | None = None) -> Pet:
    """Отметить, что питомец умер: он исчезает из напоминаний и рассылок."""
    pet.status = Pet.Status.DEAD
    pet.death_date = death_date or _today()
    return save_pet(pet)


def add_weight(pet: Pet, weight: Decimal, on: date | None = None) -> PetWeight:
    if weight <= 0 or weight > 2000:
        raise ClientError("Проверьте вес: он должен быть больше нуля и в килограммах.")
    on = on or _today()
    if on > _today():
        raise ClientError("Дата взвешивания не может быть в будущем.")
    return PetWeight.objects.create(pet=pet, weight=weight, date=on)


def current_weight(pet: Pet) -> PetWeight | None:
    return pet.weights.first()


def former_pets(client: Client) -> QuerySet[Pet]:
    """Питомцы, которых клиент передал другим владельцам."""
    return (
        Pet.objects.filter(ownerships__client=client, ownerships__date_to__isnull=False)
        .exclude(owner=client)
        .distinct()
    )


def search_pets(queryset: QuerySet[Pet], text: str) -> QuerySet[Pet]:
    """Поиск питомцев: кличка, № чипа, лабораторный №, фамилия владельца."""
    for word in text.split():
        queryset = queryset.filter(
            Q(name__icontains=word)
            | Q(chip_number__icontains=word)
            | Q(lab_number__iexact=word)
            | Q(owner__last_name__icontains=word)
        )
    return queryset.distinct()


def current_owner(pet: Pet) -> Client:
    """Текущий владелец питомца — для других модулей (счета, медкарта)."""
    return pet.owner


# --- Договоры ----------------------------------------------------------------------


def save_contract(contract: ClientContract) -> ClientContract:
    """Сохранить договор. Номер не указан — выдаётся автоматически («K1-000001»)."""
    contract.number = contract.number.strip() or core_services.next_number("contract")
    contract.date = contract.date or _today()
    if contract.valid_until and contract.valid_until < contract.date:
        raise ClientError("Срок действия договора раньше его даты.")
    if contract.attachment and (
        contract.attachment.owner_id != contract.client_id
        or contract.attachment.owner_type.model != "client"
    ):
        raise ClientError("Скан договора должен быть прикреплён к этому же клиенту.")
    contract.save()
    return contract


def active_contracts() -> QuerySet[ClientContract]:
    today = _today()
    return ClientContract.objects.filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))


def has_active_contract(client: Client) -> bool:
    return active_contracts().filter(client=client).exists()


def with_contract_flag(queryset: QuerySet[Client]) -> QuerySet[Client]:
    """Добавить к клиентам признак has_contract — есть действующий договор."""
    return queryset.annotate(has_contract=Exists(active_contracts().filter(client=OuterRef("pk"))))


def set_weight_on(pet: Pet, on: date, weight: Decimal) -> PetWeight:
    """Вес на дату (с приёма): одно взвешивание в день — повторное сохранение его обновляет."""
    if weight <= 0 or weight > 2000:
        raise ClientError("Проверьте вес: он должен быть больше нуля и в килограммах.")
    record = pet.weights.filter(date=on).first()
    if record is None:
        return PetWeight.objects.create(pet=pet, weight=weight, date=on)
    record.weight = weight
    record.save(update_fields=["weight"])
    return record


def mark_sterilized(pet: Pet) -> None:
    """Стерилизация / кастрация проведена — отметка в карточке питомца."""
    if not pet.sterilized:
        pet.sterilized = True
        pet.save(update_fields=["sterilized"])


def set_chip_number(pet: Pet, number: str) -> None:
    """Чипирование — номер чипа в карточку питомца."""
    pet.chip_number = number.strip()
    pet.save(update_fields=["chip_number"])


# --- Баланс клиента ----------------------------------------------------------------


def charge(client: Any, amount: Decimal, source: Any) -> None:
    """Начислить клиенту сумму документа (выполненный счёт) — долг растёт."""
    from clients.models import ClientLedger

    core_services.post_entry(
        ClientLedger, source, client_id=getattr(client, "pk", client), amount=amount
    )


def reverse_charges(source: Any) -> None:
    """Снять начисления документа (откат счёта)."""
    from clients.models import ClientLedger

    core_services.reverse_entries(ClientLedger, source)


def balance(client: Any) -> Decimal:
    """Баланс клиента: > 0 — аванс, < 0 — долг."""
    from django.db.models import Sum

    from clients.models import ClientLedger

    total = ClientLedger.objects.filter(client=client).aggregate(total=Sum("amount"))["total"]
    return -(total or Decimal("0"))


def pay(client: Any, amount: Decimal, source: Any) -> None:
    """Оплата или аванс от клиента — баланс уменьшается (долг гасится, растёт аванс)."""
    charge(client, -amount, source)


def current_owner_id(pet_id: Any) -> Any:
    return Pet.objects.filter(pk=pet_id).values_list("owner_id", flat=True).first()
