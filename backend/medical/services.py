"""Медкарта: публичный вход модуля.

Отвечает за: записи медкарты, диагнозы, вакцинации, текстовые и специальные шаблоны.

Другие модули обращаются к модулю только через функции этого файла.
Бизнес-правила живут здесь, а не в моделях и не в API (ENGINEERING.md).
"""

import re
from collections import Counter
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from catalog import services as catalog
from clients import services as clients
from core.html import clean
from inventory import services as inventory
from medical.models import Prevention, PreventionType, Visit, VisitDiagnosis, VisitItem
from scheduling import services as scheduling
from staff import services as staff


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
    if not visit.doctor.is_active:
        raise MedicalError("Выбранный врач уволен — выберите работающего сотрудника.")
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


def doctors() -> list[Any]:
    """Кого можно указать врачом в медкарте — работающие сотрудники."""
    return list(staff.active_users())


@transaction.atomic
def delete_visit(visit: Visit) -> None:
    """Удалить запись медкарты (мягко) вместе с её процедурами профилактики.

    Процедуры удаляются, чтобы не напоминать о них и не показывать их в отчётах.
    Отметки в карточке питомца («стерилизован», номер чипа) и вес не меняются —
    их при необходимости исправляют в карточке.
    """
    visit.preventions.all().delete()
    visit.delete()


def complete_visit(visit: Visit) -> None:
    """Приём окончен: запись на приём — «завершён»."""
    if visit.appointment is not None:
        scheduling.mark_completed(visit.appointment)


def pet_visits(pet: Any) -> QuerySet[Visit]:
    return Visit.objects.filter(pet=pet).select_related("doctor", "purpose", "result")


# --- Профилактика: вакцинации, дегельминтизация, обработки, стерилизация… ----------

K = PreventionType.Kind


def preparations(prevention_type: PreventionType) -> list[Any]:
    """Что предлагать для вида профилактики: товары и услуги с этим видом в каталоге."""
    return list(catalog.preparations(prevention_type.kind))


def _close_reminders(visit: Visit, prevention_type: PreventionType, item: Any) -> None:
    """Новая процедура закрывает ждущие напоминания: у вакцинации — по той же вакцине,
    у остальных повторяемых видов — по всему виду (любой препарат от глистов)."""
    reminders = Prevention.objects.filter(
        pet=visit.pet, type=prevention_type, reminder=Prevention.Reminder.ACTIVE
    )
    if prevention_type.kind == K.VACCINATION and item is not None:
        reminders = reminders.filter(item=item)
    reminders.update(reminder=Prevention.Reminder.CLOSED)


def _batch_note(item: Any, batch: Any) -> str:
    """Серия и срок из партии склада. Партия должна быть этого же препарата."""
    if batch is None:
        return ""
    if item is None or batch.item_id != getattr(item, "pk", item):
        raise MedicalError("Партия относится к другому препарату.")
    expiry = f", годен до {batch.expiry_date:%d.%m.%Y}" if batch.expiry_date else ""
    return f"{batch.series or 'без серии'}{expiry}"


def batches_for(item: Any) -> list[Any]:
    """Партии препарата с остатком на складе — для выбора серии в профилактике."""
    return inventory.batches_for(item)


def _validate(
    prevention_type: PreventionType,
    item: Any,
    quantity: Decimal,
    procedure_date: date,
    next_date: date | None,
    note: str,
) -> None:
    if quantity <= 0:
        raise MedicalError("Количество должно быть больше нуля.")
    if prevention_type.item_required and item is None:
        what = "вакцину" if prevention_type.kind == K.VACCINATION else "препарат"
        raise MedicalError(f"Выберите {what} — для «{prevention_type.name}» он обязателен.")
    if next_date is not None and next_date <= procedure_date:
        raise MedicalError("Дата следующей процедуры должна быть позже даты этой.")
    if prevention_type.kind == K.CHIPPING and not note.strip():
        raise MedicalError("Укажите номер чипа в примечании.")


@transaction.atomic
def add_prevention(
    visit: Visit,
    prevention_type: PreventionType,
    item: Any = None,
    quantity: Decimal = Decimal("1"),
    stage: str = "",
    next_date: date | None = None,
    batch_note: str = "",
    note: str = "",
    repeat_at: time | None = None,
    batch: Any = None,
) -> Prevention:
    """Записать профилактическую процедуру.

    - повторяемая: следующая дата (по умолчанию — через «повтор через, дней» вида);
      закрывает прежние напоминания; repeat_at — запланировать визит на дату повтора;
    - стерилизация: питомцу ставится отметка «стерилизован»;
    - чипирование: номер чипа из примечания записывается в карточку питомца.
    """
    procedure_date = timezone.localdate(visit.date)
    if prevention_type.is_one_time:
        next_date = None
    elif next_date is None and prevention_type.repeat_days:
        next_date = procedure_date + timedelta(days=prevention_type.repeat_days)
    _validate(prevention_type, item, quantity, procedure_date, next_date, note)
    batch_note = _batch_note(item, batch) or batch_note

    _close_reminders(visit, prevention_type, item)
    prevention = Prevention.objects.create(
        visit=visit, pet=visit.pet, type=prevention_type, item=item, quantity=quantity,
        date=procedure_date, stage=stage, next_date=next_date, batch=batch, batch_note=batch_note,
        note=note.strip(),
        reminder=Prevention.Reminder.CLOSED if next_date is None else Prevention.Reminder.ACTIVE,
    )  # fmt: skip
    if prevention_type.kind == K.STERILIZATION:
        clients.mark_sterilized(visit.pet)
    elif prevention_type.kind == K.CHIPPING:
        clients.set_chip_number(visit.pet, prevention.note)
    if next_date is not None and repeat_at is not None:
        zone = timezone.get_current_timezone()
        scheduling.book_repeat(
            visit.client, visit.pet, visit.doctor, datetime.combine(next_date, repeat_at, zone),
            purpose_kind="vaccination" if prevention_type.kind == K.VACCINATION else "general",
            note=f"Повтор: {prevention_type.name.lower()}{f' ({item})' if item else ''}",
        )  # fmt: skip
    return prevention


@transaction.atomic
def update_prevention(prevention: Prevention, **changes: Any) -> Prevention:
    """Исправить процедуру: препарат, количество, этап, следующую дату, серию, примечание.

    Вид процедуры не меняется — для этого удалите процедуру и запишите заново.
    Закрытое более новой процедурой напоминание при исправлении не открывается.
    """
    allowed = {"item", "quantity", "stage", "next_date", "batch", "batch_note", "note"}
    unknown = set(changes) - allowed
    if unknown:
        raise MedicalError(f"Эти поля процедуры не меняются: {', '.join(sorted(unknown))}.")
    for field, value in changes.items():
        setattr(prevention, field, value)
    prevention.note = prevention.note.strip()
    if prevention.type.is_one_time:
        prevention.next_date = None
    _validate(
        prevention.type, prevention.item, prevention.quantity, prevention.date,
        prevention.next_date, prevention.note,
    )  # fmt: skip
    if "batch" in changes or "item" in changes:
        prevention.batch_note = (
            _batch_note(prevention.item, prevention.batch) or prevention.batch_note
        )
    if prevention.next_date is None:
        prevention.reminder = Prevention.Reminder.CLOSED
    prevention.save()
    if prevention.type.kind == K.CHIPPING and "note" in changes:
        clients.set_chip_number(prevention.pet, prevention.note)
    return prevention


def pet_preventions(pet: Any) -> QuerySet[Prevention]:
    return Prevention.objects.filter(pet=pet).select_related("type", "item", "visit")


def due_preventions(until: date) -> QuerySet[Prevention]:
    """Ждущие повторы до даты — для напоминаний (модуль уведомлений, этап 7)."""
    return Prevention.objects.filter(
        reminder=Prevention.Reminder.ACTIVE, next_date__lte=until
    ).select_related("pet", "type", "item")


def prevention_summary(pet: Any) -> list[dict[str, Any]]:
    """Сводка для карточки питомца: по каждому виду последняя процедура и следующий срок.

    У вакцинаций — по каждой вакцине отдельно (бешенство и комплексная — разные сроки).
    Однократные виды показываются, даже если не проводились («не проводилась»).
    """
    today = timezone.localdate()
    rows: list[dict[str, Any]] = []
    for prevention_type in PreventionType.objects.filter(is_active=True).order_by("name"):
        records = list(pet_preventions(pet).filter(type=prevention_type))
        groups: dict[Any, Prevention] = {}
        for record in records:  # новые сверху: первая — последняя по дате
            key = record.item_id if prevention_type.kind == K.VACCINATION else None
            groups.setdefault(key, record)
        if not groups and prevention_type.kind in (K.STERILIZATION, K.CHIPPING, K.DEWORMING):
            rows.append({"type": prevention_type.name, "kind": prevention_type.kind, "last": None})
        for record in groups.values():
            waiting = record.reminder == Prevention.Reminder.ACTIVE and record.next_date
            rows.append(
                {
                    "type": prevention_type.name, "kind": prevention_type.kind,
                    "last": {
                        "id": str(record.pk), "date": record.date, "visit": str(record.visit_id),
                        "item": record.item.name if record.item else "", "note": record.note,
                    },
                    "next_date": record.next_date if waiting else None,
                    "overdue": bool(waiting and record.next_date and record.next_date < today),
                }
            )  # fmt: skip
    return rows


def prevention_report(
    mode: str,
    date_from: date,
    date_to: date,
    type_id: Any = None,
    species_id: Any = None,
) -> QuerySet[Prevention]:
    """Отчёт по профилактике.

    mode: done — проведено за период; due — срок повтора наступает в периоде;
    overdue — срок прошёл (раньше сегодняшнего дня), а новой процедуры нет.
    """
    queryset = Prevention.objects.select_related(
        "type", "item", "pet__species", "pet__owner", "visit__doctor"
    ).filter(pet__status="active")
    if mode == "done":
        queryset = queryset.filter(date__gte=date_from, date__lte=date_to)
    elif mode == "due":
        queryset = queryset.filter(
            reminder=Prevention.Reminder.ACTIVE, next_date__gte=date_from, next_date__lte=date_to
        )
    elif mode == "overdue":
        queryset = queryset.filter(
            reminder=Prevention.Reminder.ACTIVE, next_date__lt=timezone.localdate()
        )
    else:
        raise MedicalError("Неизвестный вид отчёта.")
    if type_id:
        queryset = queryset.filter(type=type_id)
    if species_id:
        queryset = queryset.filter(pet__species=species_id)
    return queryset.order_by("next_date" if mode != "done" else "-date")


def prevention_suggestions(visit: Visit) -> list[dict[str, Any]]:
    """Подсказки «записать процедуру»: в тексте отмечены препарат или услуга с видом
    профилактики, а такой процедуры в записи ещё нет."""
    done = set(visit.preventions.values_list("type__kind", "item_id"))
    done_kinds = {kind for kind, _ in done}
    types = {
        t.kind: t for t in PreventionType.objects.filter(is_active=True).order_by("created_at")
    }
    suggestions: list[dict[str, Any]] = []
    seen: set[tuple[str, Any]] = set()
    for line in visit.items.select_related("item_unit__item__group"):
        item = line.item_unit.item
        kind = catalog.prevention_kind_of(item)
        prevention_type = types.get(kind)
        if prevention_type is None or (kind, item.pk) in seen:
            continue
        seen.add((kind, item.pk))
        if (kind, item.pk) in done or (kind != K.VACCINATION and kind in done_kinds):
            continue
        suggestions.append(
            {"type": str(prevention_type.pk), "type_name": prevention_type.name,
             "kind": kind, "item": str(item.pk), "item_name": item.name}
        )  # fmt: skip
    return suggestions


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
            {"vaccine": p.item.name if p.item else "", "date": p.date, "next_date": p.next_date,
             "batch": p.batch_note}
            for p in visit.preventions.filter(type__kind=K.VACCINATION).select_related("item")
        ],
        "preventions": [
            {"type": p.type.name, "item": p.item.name if p.item else "", "date": p.date,
             "next_date": p.next_date, "batch": p.batch_note, "note": p.note}
            for p in visit.preventions.select_related("type", "item")
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
        "preventions": [{"type": "Дегельминтизация", "item": "Мильбемакс", "date": today,
                         "next_date": today, "batch": "", "note": ""}],
    }  # fmt: skip


def invoice_lines(visit: Visit) -> list[dict[str, Any]]:
    """Позиции, отмеченные в записи через «@», — для счёта: единица, количество, врач."""
    return [
        {"item_unit": line.item_unit_id, "quantity": line.quantity, "performer": visit.doctor_id}
        for line in visit.items.all()
    ]


def get_visit(pk: Any) -> Visit | None:
    return (
        Visit.objects.select_related("pet", "client", "doctor", "appointment").filter(pk=pk).first()
    )
