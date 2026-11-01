"""Стационар: публичный вход модуля.

Отвечает за: палаты, госпитализацию, лист назначений с отметками выполнения,
наблюдения, выписку и счёт за стационар.
"""

import math
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from billing import services as billing
from catalog import services as catalog
from clients import services as clients
from inpatient.models import Hospitalization, Observation, TreatmentPlan, TreatmentTask, Ward
from medical import services as medical

H = Hospitalization.Status
ROUTES = {value for value, _ in TreatmentPlan._meta.get_field("route").choices or []}
T = TreatmentTask.Status


class InpatientError(Exception):
    """Действие в стационаре невозможно. Текст — для пользователя."""


# --- Госпитализация ----------------------------------------------------------------


def occupied(ward: Ward) -> int:
    return ward.hospitalizations.filter(status=H.ACTIVE).count()


@transaction.atomic
def admit(
    pet: Any,
    ward: Ward,
    doctor: Any,
    reason: str = "",
    visit: Any = None,
    place: int | None = None,
    planned_discharge: date | None = None,
) -> Hospitalization:
    """Принять питомца в стационар. Мест в палате должно хватать; дважды — нельзя."""
    if Hospitalization.objects.filter(pet=pet, status=H.ACTIVE).exists():
        raise InpatientError(f"{pet.name} уже в стационаре.")
    if occupied(ward) >= ward.places:
        raise InpatientError(
            f"В палате «{ward}» нет свободных мест ({ward.places} из {ward.places} занято)."
        )
    if place is not None and ward.hospitalizations.filter(status=H.ACTIVE, place=place).exists():
        raise InpatientError(f"Место {place} в палате «{ward}» занято.")
    return Hospitalization.objects.create(
        pet=pet,
        client=clients.current_owner(pet),
        ward=ward,
        doctor=doctor,
        reason=reason.strip(),
        visit_id=getattr(visit, "pk", visit),
        place=place,
        planned_discharge=planned_discharge,
        admitted_at=timezone.now(),
    )


def days_count(hospitalization: Hospitalization) -> int:
    """Число суток в стационаре: каждые начатые 24 часа — сутки (минимум одни)."""
    end = hospitalization.discharged_at or timezone.now()
    hours = (end - hospitalization.admitted_at).total_seconds() / 3600
    return max(1, math.ceil(hours / 24))


def _active(hospitalization: Hospitalization) -> None:
    if hospitalization.status != H.ACTIVE:
        raise InpatientError("Пациент уже выписан.")


@transaction.atomic
def discharge(hospitalization: Hospitalization, outcome: str = "") -> Hospitalization:
    """Выписать: будущие невыполненные отметки снимаются, назначения прекращаются."""
    _active(hospitalization)
    now = timezone.now()
    hospitalization.tasks.filter(status=T.PLANNED, scheduled_at__gt=now).delete()
    hospitalization.plans.update(is_active=False)
    hospitalization.status = H.DISCHARGED
    hospitalization.discharged_at = now
    hospitalization.outcome = outcome.strip()
    hospitalization.save()
    return hospitalization


# --- Назначения и лист назначений ---------------------------------------------------

_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@transaction.atomic
def add_plan(
    hospitalization: Hospitalization,
    title: str,
    times: list[str],
    start_date: date,
    days: int = 1,
    item: Any = None,
    dose: str = "",
    route: str = "oral",
    note: str = "",
) -> TreatmentPlan:
    """Назначение: в каждый из дней — отметки на каждый указанный час."""
    _active(hospitalization)
    title = (title or (item.name if item else "")).strip()
    if not title:
        raise InpatientError("Укажите препарат или процедуру.")
    times = sorted({t.strip() for t in times if t and t.strip()})
    if not times or any(not _TIME.match(t) for t in times):
        raise InpatientError("Укажите часы в виде 08:00, 20:00.")
    if days < 1 or days > 60:
        raise InpatientError("Число дней — от 1 до 60.")
    plan = TreatmentPlan.objects.create(
        hospitalization=hospitalization,
        item=item,
        title=title,
        dose=dose.strip(),
        route=route,
        times=times,
        start_date=start_date,
        days=days,
        note=note.strip(),
    )
    zone = timezone.get_current_timezone()
    TreatmentTask.objects.bulk_create(
        TreatmentTask(
            plan=plan,
            hospitalization=hospitalization,
            scheduled_at=datetime.combine(
                start_date + timedelta(days=d), time.fromisoformat(t), zone
            ),
        )
        for d in range(days)
        for t in times
    )
    return plan


def stop_plan(plan: TreatmentPlan) -> None:
    """Отменить назначение: невыполненные будущие отметки убираются, история остаётся."""
    plan.tasks.filter(status=T.PLANNED, scheduled_at__gt=timezone.now()).delete()
    plan.is_active = False
    plan.save(update_fields=["is_active"])


def mark_task(
    task: TreatmentTask, status: str, user: Any, note: str = "", quantity: Decimal | None = None
) -> TreatmentTask:
    """Отметить выполнение (или пропуск — с причиной); вернуть в «запланировано»."""
    if status not in T.values:
        raise InpatientError("Неизвестная отметка.")
    if status == T.SKIPPED and not note.strip():
        raise InpatientError("Укажите, почему пропущено.")
    task.status = status
    task.note = note.strip()
    task.quantity = quantity
    task.done_at = timezone.now() if status != T.PLANNED else None
    task.done_by = user if status != T.PLANNED else None
    task.save()
    return task


def _times_from_frequency(text: str) -> list[str]:
    """«2 раза в день» → 08:00, 20:00; «3 раза» → 08:00, 14:00, 20:00; иначе — 09:00."""
    text = (text or "").lower()
    if "4 раза" in text or "каждые 6" in text:
        return ["06:00", "12:00", "18:00", "23:00"]
    if "3 раза" in text or "каждые 8" in text:
        return ["08:00", "14:00", "20:00"]
    if "2 раза" in text or "каждые 12" in text:
        return ["08:00", "20:00"]
    return ["09:00"]


@transaction.atomic
def import_from_visit(hospitalization: Hospitalization) -> int:
    """Перенести назначения из медкарты приёма-основания в лист назначений.

    Часы подбираются по кратности («2 раза в день» → 8:00 и 20:00) — их можно поправить.
    """
    if hospitalization.visit_id is None:
        raise InpatientError("Госпитализация не связана с приёмом в медкарте.")
    rows = medical.prescriptions_of(hospitalization.visit_id)
    today = timezone.localdate()
    for row in rows:
        add_plan(
            hospitalization,
            row["title"],
            _times_from_frequency(row["frequency"]),
            today,
            days=row["days"] or 1,
            item=catalog.get_item(row["item"]) if row["item"] else None,
            dose=row["dose"],
            route=row["route"] if row["route"] in ROUTES else "other",
            note=row["comment"],
        )
    return len(rows)


def sheet(hospitalization: Hospitalization, day: date) -> QuerySet[TreatmentTask]:
    zone = timezone.get_current_timezone()
    start = datetime.combine(day, time.min, zone)
    return hospitalization.tasks.filter(
        scheduled_at__gte=start, scheduled_at__lt=start + timedelta(days=1)
    ).select_related("plan", "done_by")


def add_observation(hospitalization: Hospitalization, user: Any, **values: Any) -> Observation:
    if not any(values.get(k) not in (None, "") for k in ("temperature", "weight", "pulse", "note")):
        raise InpatientError("Заполните хотя бы одно поле наблюдения.")
    t = values.get("temperature")
    if t is not None and not Decimal("30") <= Decimal(str(t)) <= Decimal("45"):
        raise InpatientError("Проверьте температуру: обычно от 30 до 45 °C.")
    return Observation.objects.create(
        hospitalization=hospitalization,
        author=user,
        at=values.pop("at", None) or timezone.now(),
        **values,
    )


# --- Счёт ---------------------------------------------------------------------------


@transaction.atomic
def create_invoice(hospitalization: Hospitalization) -> Any:
    """Черновик счёта за стационар: сутки по услуге палаты + выполненные назначения из прайса.

    Повторно — создаётся новый черновик (прежний можно удалить или выполнить).
    """
    lines: list[billing.LineData] = []
    if hospitalization.ward.daily_item_id:
        unit = catalog.sale_unit(hospitalization.ward.daily_item_id)
        if unit is not None:
            lines.append(
                {
                    "item_unit": unit,
                    "quantity": Decimal(days_count(hospitalization)),
                    "performer": hospitalization.doctor_id,
                }
            )
    used: dict[Any, Decimal] = {}
    for task in (
        hospitalization.tasks.filter(status=T.DONE).exclude(plan__item=None).select_related("plan")
    ):
        used[task.plan.item_id] = used.get(task.plan.item_id, Decimal("0")) + (
            task.quantity or Decimal("1")
        )
    for item_id, qty in used.items():
        unit = catalog.sale_unit(item_id)
        if unit is not None:
            lines.append(
                {"item_unit": unit, "quantity": qty, "performer": hospitalization.doctor_id}
            )
    if not lines:
        raise InpatientError(
            "Нечего выставлять: у палаты нет услуги «сутки», выполненных назначений из прайса нет."
        )
    invoice_id = billing.create_invoice(
        hospitalization.client_id,
        lines,
        pet=hospitalization.pet_id,
        doctor=hospitalization.doctor_id,
        comment=f"Стационар: {hospitalization.ward}, {days_count(hospitalization)} сут.",
    )
    hospitalization.invoice_id = invoice_id
    hospitalization.save(update_fields=["invoice_id"])
    return invoice_id


def active() -> QuerySet[Hospitalization]:
    return Hospitalization.objects.filter(status=H.ACTIVE).select_related(
        "pet", "client", "ward", "doctor"
    )


# --- Печать -------------------------------------------------------------------------


def sheet_context(hospitalization: Hospitalization, day: date) -> dict[str, Any]:
    """Лист назначений на день — для печати и подписи персонала."""
    pet = hospitalization.pet
    return {
        "pet": {"name": pet.name, "species": pet.species.name, "breed": pet.breed.name},
        "client": {"full_name": hospitalization.client.full_name},
        "doctor": {"full_name": hospitalization.doctor.full_name},
        "ward": hospitalization.ward.name,
        "place": hospitalization.place,
        "day": day,
        "day_number": (day - timezone.localdate(hospitalization.admitted_at)).days + 1,
        "reason": hospitalization.reason,
        "tasks": [
            {
                "time": f"{timezone.localtime(t.scheduled_at):%H:%M}",
                "title": t.plan.title,
                "dose": t.plan.dose,
                "route": t.plan.get_route_display(),
                "status": t.get_status_display(),
                "done_by": t.done_by.short_name if t.done_by else "",
                "note": t.note,
            }
            for t in sheet(hospitalization, day)
        ],
    }


def sample_sheet_context() -> dict[str, Any]:
    today = timezone.localdate()
    return {
        "pet": {"name": "Барсик", "species": "Кошки", "breed": "Метис"},
        "client": {"full_name": "Иванова Анна Петровна"},
        "doctor": {"full_name": "Петров Пётр Петрович"},
        "ward": "Палата 1",
        "place": 2,
        "day": today,
        "day_number": 2,
        "reason": "Гастроэнтерит",
        "tasks": [
            {
                "time": "08:00",
                "title": "Церукал",
                "dose": "0,3 мл",
                "route": "подкожно",
                "status": "выполнено",
                "done_by": "Сидорова О.",
                "note": "",
            },
        ],
    }
