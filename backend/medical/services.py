"""Медкарта: публичный вход модуля.

Отвечает за: записи медкарты, диагнозы, вакцинации, текстовые и специальные шаблоны.

Другие модули обращаются к модулю только через функции этого файла.
Бизнес-правила живут здесь, а не в моделях и не в API (ENGINEERING.md).
"""

import re
from collections import Counter
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from catalog import services as catalog
from clients import services as clients
from core.html import clean
from medical.models import Vaccination, Visit, VisitDiagnosis, VisitItem
from scheduling import services as scheduling


class MedicalError(Exception):
    """Ошибка в записи медкарты. Текст — для пользователя."""


MENTION = re.compile(r'data-item-unit="([0-9a-fA-F-]{36})"')


def mentioned_units(html: str) -> Counter[str]:
    """Позиции прайса, отмеченные в тексте через «@»: id единицы → сколько раз отмечена."""
    return Counter(MENTION.findall(html or ""))


# --- Запись медкарты ---------------------------------------------------------------


def start_visit(pet: Any, doctor: Any, appointment: Any = None) -> Visit:
    """Новая запись медкарты. По записи на приём — с её целью, а приём становится «у врача»."""
    purpose = (appointment.purpose if appointment else None) or scheduling.default_purpose()
    if purpose is None:
        raise MedicalError("Нет ни одной цели обращения — добавьте их в справочник.")
    with transaction.atomic():
        visit = Visit.objects.create(
            pet=pet, client=clients.current_owner(pet), doctor=doctor, date=timezone.now(),
            purpose=purpose, appointment=appointment,
            weight=_last_weight(pet),
        )  # fmt: skip
        if appointment is not None:
            scheduling.mark_in_progress(appointment)
    return visit


def _last_weight(pet: Any) -> Decimal | None:
    latest = clients.current_weight(pet)
    return latest.weight if latest else None


def visit_for_appointment(appointment: Any, doctor: Any) -> Visit:
    """Запись медкарты по записи на приём: уже начатая или новая."""
    existing = Visit.objects.filter(appointment=appointment).first()
    if existing is not None:
        scheduling.mark_in_progress(appointment)
        return existing
    if appointment.pet_id is None:
        raise MedicalError("В записи на приём нет карточки питомца — сначала заведите питомца.")
    return start_visit(appointment.pet, appointment.doctor or doctor, appointment)


@transaction.atomic
def save_visit(visit: Visit, diagnoses: list[tuple[Any, str]] | None = None) -> Visit:
    """Сохранить запись: очистить текст, собрать позиции из «@», записать вес питомцу."""
    if visit.temperature is not None and not Decimal("30") <= visit.temperature <= Decimal("45"):
        raise MedicalError("Проверьте температуру: обычно от 30 до 45 °C.")
    if visit.weight is not None and visit.weight <= 0:
        raise MedicalError("Вес должен быть больше нуля.")
    visit.treatment_html = clean(visit.treatment_html)
    visit.recommendations_html = clean(visit.recommendations_html)
    visit.save()
    _sync_items(visit)
    if diagnoses is not None:
        visit.diagnoses.all().delete()
        VisitDiagnosis.objects.bulk_create(
            VisitDiagnosis(visit=visit, diagnosis_id=getattr(d, "pk", d), kind=kind)
            for d, kind in diagnoses
        )
    if visit.weight is not None:
        try:
            clients.set_weight_on(visit.pet, timezone.localtime(visit.date).date(), visit.weight)
        except clients.ClientError as error:
            raise MedicalError(str(error)) from error
    return visit


def _sync_items(visit: Visit) -> None:
    visit.items.all().delete()
    rows = []
    for section, html in (
        (VisitItem.Section.TREATMENT, visit.treatment_html),
        (VisitItem.Section.RECOMMENDATIONS, visit.recommendations_html),
    ):
        counts = mentioned_units(html)
        known = {str(u.pk) for u in catalog.item_units(list(counts))}
        rows += [
            VisitItem(visit=visit, item_unit_id=pk, quantity=Decimal(n), section=section)
            for pk, n in counts.items()
            if pk in known
        ]
    VisitItem.objects.bulk_create(rows)


def complete_visit(visit: Visit) -> None:
    """Приём окончен: запись на приём — «завершён»."""
    if visit.appointment is not None:
        scheduling.mark_completed(visit.appointment)


def pet_visits(pet: Any) -> QuerySet[Visit]:
    return Visit.objects.filter(pet=pet).select_related("doctor", "purpose", "result")


# --- Вакцинации --------------------------------------------------------------------


@transaction.atomic
def add_vaccination(
    visit: Visit,
    vaccine: Any,
    quantity: Decimal = Decimal("1"),
    kind: str = Vaccination.Kind.PRIMARY,
    next_date: date | None = None,
    batch_note: str = "",
    repeat_at: time | None = None,
) -> Vaccination:
    """Записать вакцинацию.

    Действующие напоминания по этой же вакцине у питомца закрываются — клиенту
    не придёт напоминание о том, что уже сделано. repeat_at — запланировать
    визит на дату повтора в это время.
    """
    vaccination_date = timezone.localtime(visit.date).date()
    if quantity <= 0:
        raise MedicalError("Количество должно быть больше нуля.")
    if next_date is not None and next_date <= vaccination_date:
        raise MedicalError("Дата следующей вакцинации должна быть позже сегодняшней.")
    Vaccination.objects.filter(
        pet=visit.pet, vaccine=vaccine, reminder=Vaccination.Reminder.ACTIVE
    ).update(reminder=Vaccination.Reminder.CLOSED)
    vaccination = Vaccination.objects.create(
        visit=visit, pet=visit.pet, vaccine=vaccine, quantity=quantity, date=vaccination_date,
        kind=kind, next_date=next_date, batch_note=batch_note,
    )  # fmt: skip
    if next_date is not None and repeat_at is not None:
        zone = timezone.get_current_timezone()
        scheduling.book_repeat(
            visit.client, visit.pet, visit.doctor, datetime.combine(next_date, repeat_at, zone),
            purpose_kind="vaccination", note=f"Ревакцинация: {vaccine}",
        )  # fmt: skip
    return vaccination


def pet_vaccinations(pet: Any) -> QuerySet[Vaccination]:
    return Vaccination.objects.filter(pet=pet).select_related("vaccine", "visit")


def due_vaccinations(until: date) -> QuerySet[Vaccination]:
    """Ждущие повторы до даты — для напоминаний (модуль уведомлений, этап 7)."""
    return Vaccination.objects.filter(
        reminder=Vaccination.Reminder.ACTIVE, next_date__lte=until
    ).select_related("pet", "vaccine")


# --- Печать ------------------------------------------------------------------------


def print_context(visit: Visit) -> dict[str, Any]:
    """Данные для печатной формы «Медкарта» — словари, не объекты базы."""
    pet = visit.pet
    return {
        "pet": {
            "name": pet.name, "species": pet.species.name, "breed": pet.breed.name,
            "sex": pet.get_sex_display(), "birth_date": pet.birth_date, "chip": pet.chip_number,
        },
        "client": {"full_name": visit.client.full_name},
        "doctor": {"full_name": visit.doctor.full_name, "short_name": visit.doctor.short_name},
        "visit": {
            "date": visit.date, "purpose": visit.purpose.name,
            "result": visit.result.name if visit.result else "",
            "weight": visit.weight, "temperature": visit.temperature,
            "diagnoses": ", ".join(d.diagnosis.name for d in visit.diagnoses.all()),
            "treatment": visit.treatment_html, "recommendations": visit.recommendations_html,
            "next_visit_date": visit.next_visit_date,
        },
        "vaccinations": [
            {"vaccine": v.vaccine.name, "date": v.date, "next_date": v.next_date,
             "batch": v.batch_note}
            for v in visit.vaccinations.all()
        ],
    }  # fmt: skip


def sample_print_context() -> dict[str, Any]:
    today = timezone.localdate()
    return {
        "pet": {"name": "Барсик", "species": "Кошки", "breed": "Метис", "sex": "самец",
                "birth_date": date(2022, 5, 1), "chip": "643094100123456"},
        "client": {"full_name": "Иванова Анна Петровна"},
        "doctor": {"full_name": "Петров Пётр Петрович", "short_name": "Петров П. П."},
        "visit": {"date": timezone.now(), "purpose": "Первичный", "result": "Улучшение",
                  "weight": Decimal("4.25"), "temperature": Decimal("38.6"),
                  "diagnoses": "Гастроэнтерит", "treatment": "<p>Осмотр. Назначено лечение.</p>",
                  "recommendations": "<p>Диета 5 дней.</p>", "next_visit_date": today},
        "vaccinations": [],
    }  # fmt: skip
