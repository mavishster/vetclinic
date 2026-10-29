"""Сотрудники: публичный вход модуля.

Отвечает за: сотрудников, график работы.

Другие модули обращаются к модулю только через функции этого файла.
Бизнес-правила живут здесь, а не в моделях и не в API (ENGINEERING.md).
"""

from datetime import date, datetime, time, timedelta
from typing import Any, TypedDict

from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from core import services as core_services
from core.models import User
from staff.models import Employee, IntervalTemplate, WorkInterval

# Рабочий интервал длиннее этого — почти наверняка ошибка ввода (сутки + запас).
MAX_WORKING_HOURS = 36


class StaffError(Exception):
    """Ошибка в данных сотрудника или графика. Текст — для пользователя."""


# --- Сотрудник ---------------------------------------------------------------------


@transaction.atomic
def save_employee(
    employee: Employee,
    user: User,
    password: str | None = None,
    roles: list[Group] | None = None,
) -> Employee:
    """Создать или изменить сотрудника вместе с учётной записью."""
    try:
        core_services.save_user_account(user, password=password, roles=roles)
    except core_services.UserError as error:
        raise StaffError(str(error)) from error
    if employee._state.adding:
        # Профиль новой учётной записи уже создан автоматически — заполняем его.
        profile, _ = Employee.objects.get_or_create(user=user)
        for field in ("position", "phone", "color", "in_schedule"):
            setattr(profile, field, getattr(employee, field))
        employee = profile
    employee.save()
    return employee


# --- График ------------------------------------------------------------------------


def _overlaps(interval: WorkInterval) -> QuerySet[WorkInterval]:
    return WorkInterval.objects.filter(
        user=interval.user, start__lt=interval.end, end__gt=interval.start
    ).exclude(pk=interval.pk)


def save_interval(interval: WorkInterval) -> WorkInterval:
    """Сохранить интервал графика: конец позже начала, без пересечений у сотрудника."""
    if interval.end <= interval.start:
        raise StaffError("Конец интервала должен быть позже начала.")
    hours = (interval.end - interval.start).total_seconds() / 3600
    if interval.interval_type.is_working and hours > MAX_WORKING_HOURS:
        raise StaffError(f"Рабочий интервал длиннее {MAX_WORKING_HOURS} часов — проверьте даты.")
    clash = _overlaps(interval).select_related("interval_type").first()
    if clash is not None:
        local = timezone.localtime
        raise StaffError(
            f"Пересекается с интервалом «{clash.interval_type}» "
            f"{local(clash.start):%d.%m %H:%M}–{local(clash.end):%d.%m %H:%M}."
        )
    interval.save()
    return interval


def template_period(day: date, template: IntervalTemplate) -> tuple[datetime, datetime]:
    """Начало и конец по шаблону на дату. Конец не позже начала — значит, на следующий день."""
    zone = timezone.get_current_timezone()
    start = datetime.combine(day, template.start_time, tzinfo=zone)
    end = datetime.combine(day, template.end_time, tzinfo=zone)
    if end <= start:
        end += timedelta(days=1)
    return start, end


class FillResult(TypedDict):
    created: int
    skipped: list[str]  # почему не создано: пересечения


def apply_template(users: list[User], days: list[date], template: IntervalTemplate) -> FillResult:
    """Заполнить график по шаблону: сотрудники × даты. Пересечения пропускаются."""
    result: FillResult = {"created": 0, "skipped": []}
    for user in users:
        for day in days:
            start, end = template_period(day, template)
            interval = WorkInterval(
                user=user, start=start, end=end, interval_type=template.interval_type
            )
            try:
                save_interval(interval)
                result["created"] += 1
            except StaffError as error:
                result["skipped"].append(f"{user.short_name or user}, {day:%d.%m}: {error}")
    return result


def copy_week(source_monday: date, target_monday: date) -> FillResult:
    """Скопировать график недели на другую неделю. Пересечения пропускаются."""
    if source_monday.weekday() != 0 or target_monday.weekday() != 0:
        raise StaffError("Неделя задаётся понедельником.")
    zone = timezone.get_current_timezone()
    week_start = datetime.combine(source_monday, time.min, tzinfo=zone)
    shift = timedelta(days=(target_monday - source_monday).days)
    result: FillResult = {"created": 0, "skipped": []}
    source = WorkInterval.objects.filter(
        start__gte=week_start, start__lt=week_start + timedelta(days=7)
    ).select_related("user", "interval_type")
    for original in source:
        copy = WorkInterval(
            user=original.user,
            start=original.start + shift,
            end=original.end + shift,
            interval_type=original.interval_type,
            comment=original.comment,
        )
        try:
            save_interval(copy)
            result["created"] += 1
        except StaffError as error:
            day = timezone.localtime(copy.start)
            result["skipped"].append(f"{original.user.short_name}, {day:%d.%m}: {error}")
    return result


def intervals_between(start: datetime, end: datetime) -> QuerySet[WorkInterval]:
    """Интервалы, задевающие период (для экрана графика)."""
    return WorkInterval.objects.filter(start__lt=end, end__gt=start).select_related(
        "user", "interval_type"
    )


def is_on_shift(user: Any, at: datetime | None = None) -> bool:
    """Работает ли сотрудник в этот момент (рабочий интервал графика).

    Нужно счёту и медкарте: первыми в списке исполнителей — те, кто в смене.
    """
    at = at or timezone.now()
    return WorkInterval.objects.filter(
        user=user, start__lte=at, end__gt=at, interval_type__is_working=True
    ).exists()


def on_shift_user_ids(at: datetime | None = None) -> set[Any]:
    at = at or timezone.now()
    return set(
        WorkInterval.objects.filter(
            start__lte=at, end__gt=at, interval_type__is_working=True
        ).values_list("user_id", flat=True)
    )
