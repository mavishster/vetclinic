"""График работы: интервалы, пересечения, шаблоны, копирование недели, «кто в смене»."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model

from staff import services
from staff.models import Employee, IntervalTemplate, IntervalType, WorkInterval
from staff.services import StaffError

MSK = ZoneInfo("Asia/Bishkek")


def at(day: int, hour: int, month: int = 11) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=MSK)


@pytest.fixture
def doctor(db):
    return get_user_model().objects.create_user(username="doc", password="x", last_name="Иванова")


def interval(user, start, end, type_name="Приём"):
    return services.save_interval(
        WorkInterval(
            user=user, start=start, end=end, interval_type=IntervalType.objects.get(name=type_name)
        )
    )


def test_every_user_gets_employee_profile(doctor) -> None:
    assert Employee.objects.filter(user=doctor).exists()


def test_end_after_start_and_reasonable_length(doctor) -> None:
    with pytest.raises(StaffError, match="позже начала"):
        interval(doctor, at(2, 9), at(2, 9))
    with pytest.raises(StaffError, match="длиннее"):
        interval(doctor, at(2, 9), at(4, 9))
    interval(doctor, at(2, 0), at(16, 0), "Отпуск")  # нерабочий может быть длинным


def test_intervals_do_not_overlap_but_can_touch(doctor) -> None:
    interval(doctor, at(2, 9), at(2, 15))
    interval(doctor, at(2, 15), at(2, 21), "Дежурство")

    with pytest.raises(
        StaffError, match="Пересекается с интервалом «Приём» 02.11 09:00–02.11 15:00"
    ):
        interval(doctor, at(2, 14), at(2, 16))


def test_night_template_ends_next_day(doctor) -> None:
    night = IntervalTemplate.objects.get(name="Ночная 21–9")
    day_shift = IntervalTemplate.objects.get(name="Сутки 9–9")

    start, end = services.template_period(date(2026, 11, 2), night)
    assert (start, end) == (at(2, 21), at(3, 9))
    assert services.template_period(date(2026, 11, 2), day_shift)[1] == at(3, 9)


def test_fill_by_template_skips_conflicts(doctor) -> None:
    other = get_user_model().objects.create_user(username="doc2", password="x", last_name="Петров")
    interval(doctor, at(3, 10), at(3, 12))
    template = IntervalTemplate.objects.get(name="Дневная 9–21")

    result = services.apply_template(
        [doctor, other], [date(2026, 11, 2), date(2026, 11, 3)], template
    )

    assert result["created"] == 3
    assert len(result["skipped"]) == 1
    assert "Иванова, 03.11" in result["skipped"][0]


def test_copy_week_shifts_intervals_and_skips_conflicts(doctor) -> None:
    interval(doctor, at(2, 9), at(2, 21))  # понедельник
    interval(doctor, at(8, 21), at(9, 9), "Дежурство")  # ночь с воскресенья на понедельник
    interval(doctor, at(10, 12), at(10, 14))  # на целевой неделе уже что-то есть во вторник
    interval(doctor, at(3, 9), at(3, 21))  # вторник исходной недели — пересечётся

    result = services.copy_week(date(2026, 11, 2), date(2026, 11, 9))

    assert result["created"] == 2
    assert len(result["skipped"]) == 1
    copied = WorkInterval.objects.filter(start__gte=at(9, 9)).exclude(start=at(10, 12))
    assert sorted((c.start, c.end) for c in copied) == [
        (at(9, 9), at(9, 21)),
        (at(15, 21), at(16, 9)),
    ]


def test_copy_week_requires_mondays(doctor) -> None:
    with pytest.raises(StaffError, match="понедельником"):
        services.copy_week(date(2026, 11, 3), date(2026, 11, 10))


def test_is_on_shift_counts_only_working_intervals(doctor) -> None:
    interval(doctor, at(2, 9), at(2, 21))
    interval(doctor, at(5, 0), at(10, 0), "Отпуск")

    assert services.is_on_shift(doctor, at(2, 12))
    assert not services.is_on_shift(doctor, at(2, 22))
    assert not services.is_on_shift(doctor, at(6, 12))
    assert services.on_shift_user_ids(at(2, 12)) == {doctor.pk}
