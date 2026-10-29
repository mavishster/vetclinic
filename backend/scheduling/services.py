"""Календарь и приёмы: публичный вход модуля.

Отвечает за: запись на приём, статусы приёма, календарь.

Другие модули обращаются к модулю только через функции этого файла.
Бизнес-правила живут здесь, а не в моделях и не в API (ENGINEERING.md).
"""

from datetime import date, datetime, timedelta
from typing import Any

from django.db.models import Q, QuerySet
from django.utils import timezone

from clients import services as clients
from clients.models import Client
from scheduling.models import Appointment, VisitPurpose
from staff import services as staff

S = Appointment.Status

# Через сколько минут после начала запланированная запись подсвечивается как просроченная.
OVERDUE_AFTER_MINUTES = 30
ACTIVE = (S.PLANNED, S.WAITING, S.IN_PROGRESS)

# Какие переходы статусов разрешены (откуда → куда).
TRANSITIONS: dict[str, set[str]] = {
    S.PLANNED: {S.WAITING, S.IN_PROGRESS, S.CANCELLED, S.NO_SHOW},
    S.WAITING: {S.IN_PROGRESS, S.PLANNED, S.CANCELLED},
    S.IN_PROGRESS: {S.COMPLETED, S.WAITING},
    S.COMPLETED: {S.IN_PROGRESS},
    S.CANCELLED: {S.PLANNED},
    S.NO_SHOW: {S.PLANNED, S.WAITING},
}


class AppointmentError(Exception):
    """Запись невозможна. Текст — для пользователя."""


class AppointmentWarning(Exception):
    """Запись возможна, но есть то, что стоит проверить (врач занят, не в графике…)."""

    def __init__(self, warnings: list[str]) -> None:
        super().__init__("; ".join(warnings))
        self.warnings = warnings


def _local(moment: datetime) -> str:
    return f"{timezone.localtime(moment):%H:%M}"


def check_appointment(appointment: Appointment) -> list[str]:
    """Предупреждения по записи — не запрещают её, но их стоит увидеть до сохранения."""
    warnings: list[str] = []
    others = Appointment.objects.filter(status__in=ACTIVE).exclude(pk=appointment.pk)
    if appointment.doctor_id:
        busy = others.filter(
            doctor_id=appointment.doctor_id, start__lt=appointment.end, end__gt=appointment.start
        ).first()
        if busy is not None:
            period = f"{_local(busy.start)}–{_local(busy.end)}"
            warnings.append(f"Врач в это время уже занят: {period}, {busy.client}.")
        if not staff.is_on_shift(appointment.doctor_id, appointment.start):
            warnings.append("Врач не в графике в это время.")
    day = timezone.localtime(appointment.start).date()
    same_day = others.filter(client_id=appointment.client_id, start__date=day).first()
    if same_day is not None:
        warnings.append(f"Клиент уже записан на этот день: {_local(same_day.start)}.")
    return warnings


def save_appointment(appointment: Appointment, force: bool = False) -> Appointment:
    """Сохранить запись. Без force при предупреждениях — AppointmentWarning."""
    if appointment.end <= appointment.start:
        raise AppointmentError("Конец приёма должен быть позже начала.")
    pet = appointment.pet
    if pet is not None and clients.current_owner(pet).pk != appointment.client_id:
        raise AppointmentError("Питомец принадлежит другому клиенту.")
    if not force:
        warnings = check_appointment(appointment)
        if warnings:
            raise AppointmentWarning(warnings)
    appointment.save()
    return appointment


def default_end(start: datetime, purpose: VisitPurpose | None) -> datetime:
    return start + timedelta(minutes=purpose.duration_minutes if purpose else 30)


def quick_client(last_name: str, first_name: str, phone: str) -> Client:
    """Временный клиент для быстрой записи по телефону: имя и телефон.

    Полную карточку заполнят, когда клиент придёт («временный» → «активный»).
    """
    client = Client(last_name=last_name, first_name=first_name, status=Client.Status.TEMPORARY)
    try:
        return clients.save_client(client, [{"number": phone}] if phone else [])
    except clients.ClientError as error:
        raise AppointmentError(str(error)) from error


# --- Статусы -----------------------------------------------------------------------


def change_status(appointment: Appointment, status: str, reason: str = "") -> Appointment:
    """Перевести запись в другой статус по правилам TRANSITIONS, с отметками времени."""
    if status not in TRANSITIONS.get(appointment.status, set()):
        raise AppointmentError(
            f"Нельзя перевести запись из «{appointment.get_status_display()}» "
            f"в «{S(status).label}»."
        )
    now = timezone.now()
    if status == S.WAITING:
        appointment.arrived_at = appointment.arrived_at or now
    elif status == S.IN_PROGRESS:
        appointment.arrived_at = appointment.arrived_at or now
        appointment.started_at = appointment.started_at or now
    elif status == S.COMPLETED:
        appointment.completed_at = now
    elif status == S.CANCELLED:
        if not reason.strip():
            raise AppointmentError("Укажите причину отмены.")
        appointment.cancel_reason = reason.strip()
    if status == S.PLANNED:
        appointment.arrived_at = appointment.started_at = None
        appointment.cancel_reason = ""
    appointment.status = status
    appointment.save()
    return appointment


def walk_in(appointment: Appointment) -> Appointment:
    """Клиент пришёл без записи: запись создаётся сразу в статусе «ожидает»."""
    now = timezone.now()
    appointment.start = now
    appointment.end = default_end(now, appointment.purpose)
    appointment.status = S.WAITING
    appointment.arrived_at = now
    appointment.source = Appointment.Source.WALK_IN
    return save_appointment(appointment, force=True)


# --- Выборки -----------------------------------------------------------------------


def is_overdue(appointment: Appointment, now: datetime | None = None) -> bool:
    now = now or timezone.now()
    limit = appointment.start + timedelta(minutes=OVERDUE_AFTER_MINUTES)
    return appointment.status == S.PLANNED and limit < now


def between(start: datetime, end: datetime) -> QuerySet[Appointment]:
    return Appointment.objects.filter(start__lt=end, end__gt=start).select_related(
        "client", "pet", "doctor", "purpose"
    )


def day_bounds(day: date) -> tuple[datetime, datetime]:
    zone = timezone.get_current_timezone()
    start = datetime.combine(day, datetime.min.time(), zone)
    return start, start + timedelta(days=1)


def active_for(pet: Any, day: date | None = None) -> Appointment | None:
    """Активный приём питомца на дату — медкарта и счёт подставят его сами (ADR-010)."""
    start, end = day_bounds(day or timezone.localdate())
    order: dict[str, int] = {S.IN_PROGRESS: 0, S.WAITING: 1, S.PLANNED: 2}
    found = list(
        Appointment.objects.filter(pet=pet, status__in=ACTIVE, start__gte=start, start__lt=end)
    )
    found.sort(key=lambda a: (order[a.status], a.start))
    return found[0] if found else None


def upcoming_for_client(client: Client) -> QuerySet[Appointment]:
    return Appointment.objects.filter(
        Q(client=client), status__in=ACTIVE, end__gte=timezone.now()
    ).select_related("pet", "doctor", "purpose")
