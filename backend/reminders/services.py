"""Напоминания: публичный вход модуля.

Отвечает за: сбор напоминаний из профилактики, записей и повторных приёмов, обзвон.
Рассылка (SMS, Telegram) подключится к этим же напоминаниям, когда клиника выберет канал.
"""

from datetime import date, timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from medical import services as medical
from reminders.models import Reminder
from scheduling import services as scheduling

K, S = Reminder.Kind, Reminder.Status
ACTIVE = (S.OPEN, S.NO_ANSWER)


class ReminderError(Exception):
    """Действие с напоминанием невозможно. Текст — для пользователя."""


def _upsert(kind: str, source_id: Any, **fields: Any) -> None:
    """Создать напоминание, если его ещё нет (повторный сбор не плодит дубли)."""
    Reminder.objects.get_or_create(kind=kind, source_id=source_id, defaults=fields)


@transaction.atomic
def refresh(today: date | None = None) -> None:
    """Собрать новые напоминания и закрыть те, повод для которых исчез.

    - профилактика — за PREVENTION_REMIND_DAYS дней до срока (и просроченная);
    - запись на приём — накануне;
    - повторный приём — за 3 дня до даты, которую указал врач.
    """
    today = today or timezone.localdate()
    ahead = getattr(settings, "PREVENTION_REMIND_DAYS", 7)
    for p in medical.due_preventions(today + timedelta(days=ahead)):
        what = f"{p.type.name}{f': {p.item}' if p.item else ''}"
        _upsert(
            K.PREVENTION,
            p.pk,
            client_id=p.pet.owner_id,
            pet=p.pet,
            due_date=p.next_date,
            text=f"{what} — срок {p.next_date:%d.%m.%Y}",
        )
    tomorrow = today + timedelta(days=1)
    for a in scheduling.planned_on(tomorrow):
        start = timezone.localtime(a.start)
        purpose = f" — {a.purpose.name.lower()}" if a.purpose else ""
        _upsert(
            K.APPOINTMENT,
            a.pk,
            client=a.client,
            pet=a.pet,
            due_date=start.date(),
            text=f"Приём {start:%d.%m в %H:%M}{purpose}",
        )
    for v in medical.revisits_due(today + timedelta(days=3)):
        _upsert(
            K.REVISIT,
            v.pk,
            client=v.client,
            pet=v.pet,
            due_date=v.next_visit_date,
            text=f"Повторный приём {v.next_visit_date:%d.%m.%Y}",
        )
    _close_resolved(today)


def _close_resolved(today: date) -> None:
    for reminder in Reminder.objects.filter(status__in=ACTIVE):
        if reminder.kind == K.APPOINTMENT:
            gone = reminder.due_date < today or not scheduling.is_planned(reminder.source_id)
            if gone:
                _set(reminder, S.OBSOLETE, note="запись уже прошла или отменена")
            continue
        still = (
            medical.prevention_still_due(reminder.source_id)
            if reminder.kind == K.PREVENTION
            else medical.visit_still_needs_revisit(reminder.source_id)
        )
        if not still:
            _set(reminder, S.OBSOLETE, note="уже сделано")
        elif scheduling.booked_since(reminder.client_id, reminder.pet_id, reminder.created_at):
            _set(reminder, S.BOOKED, note="клиент записался")


def _set(reminder: Reminder, status: str, note: str = "", user: Any = None) -> Reminder:
    reminder.status = status
    if note:
        reminder.note = note
    if user is not None:
        reminder.contacted_by = user
        reminder.last_contact_at = timezone.now()
    reminder.save()
    return reminder


def mark(reminder: Reminder, status: str, user: Any, note: str = "") -> Reminder:
    """Итог звонка: не дозвонились (попытка +1, остаётся в списке), напомнили, отказ, записался."""
    if status not in {S.NO_ANSWER, S.DONE, S.DECLINED, S.BOOKED, S.OPEN}:
        raise ReminderError("Неизвестный итог звонка.")
    if status == S.NO_ANSWER:
        reminder.attempts += 1
    return _set(reminder, status, note.strip(), user)


def to_call(kind: str | None = None, include_future: bool = True) -> QuerySet[Reminder]:
    """Список для обзвона: открытые и «не дозвонились»."""
    queryset = Reminder.objects.filter(status__in=ACTIVE).select_related("client", "pet")
    if kind:
        queryset = queryset.filter(kind=kind)
    return queryset.prefetch_related("client__phones")


def for_client(client: Any) -> QuerySet[Reminder]:
    return Reminder.objects.filter(client=client).order_by("-due_date")


def count_to_call() -> int:
    return Reminder.objects.filter(status__in=ACTIVE).count()
