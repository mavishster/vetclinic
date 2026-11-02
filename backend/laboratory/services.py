"""Лаборатория: публичный вход модуля.

Отвечает за: приём результатов с анализаторов, показатели и нормы, привязку результатов
к медкарте, нераспределённые результаты, динамику показателей.
"""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, TypedDict

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from clients import services as clients
from laboratory.models import Analyte, AnalyteNorm, LabResult, LabValue
from medical import services as medical

F = LabValue.Flag


class LabError(Exception):
    """Действие с результатом невозможно. Текст — для пользователя."""


class IncomingValue(TypedDict, total=False):
    code: str  # код прибора (WBC, ALT…)
    name: str  # название, если прибор прислал
    value: str
    unit: str
    reference: str
    flag: str


# --- Отметка ↑↓ (та же логика, что в LabService клиники) ----------------------------

_NUMBER = r"[-+]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][-+]?\d+)?"
_RANGE = re.compile(rf"^\s*({_NUMBER})\s*[-–]\s*({_NUMBER})(?:\s+.*)?\s*$")
_VALUE = re.compile(rf"^\s*[<>=≤≥]*\s*({_NUMBER})")
_FLAGS = {
    "H": F.HIGH,
    "HH": F.HIGH,
    "HIGH": F.HIGH,
    "L": F.LOW,
    "LL": F.LOW,
    "LOW": F.LOW,
    "N": F.NORMAL,
    "NORMAL": F.NORMAL,
    "NORMAL RANGE": F.NORMAL,
    "NR": F.NORMAL,
    "OK": F.NORMAL,
}


def numeric(value: str) -> Decimal | None:
    match = _VALUE.match(str(value or ""))
    if not match:
        return None
    try:
        return Decimal(match.group(1).replace(",", "."))
    except InvalidOperation:
        return None


def flag_of(value: str, reference: str, device_flag: str, norm: AnalyteNorm | None = None) -> str:
    """Отметка: флаг прибора → его референс → норма вида из справочника."""
    text = str(value or "").strip().lower()
    if text in {"positive", "pos", "положительно", "+"}:
        return F.POSITIVE
    known = _FLAGS.get(str(device_flag or "").strip().upper())
    if known:
        return known
    number = numeric(value)
    if number is None:
        return F.NONE
    low = high = None
    match = _RANGE.fullmatch(str(reference or ""))
    if match:
        low, high = (Decimal(v.replace(",", ".")) for v in match.groups())
    elif norm is not None:
        low, high = norm.low, norm.high
    if high is not None and number > high:
        return F.HIGH
    if low is not None and number < low:
        return F.LOW
    return F.NORMAL if (low is not None or high is not None) else F.NONE


# --- Приём результатов ----------------------------------------------------------------


def _analyte(code: str, name: str, unit: str) -> Analyte:
    code = (code or name).strip()[:50]
    found = Analyte.objects.filter(code=code).first()
    if found is not None:
        return found
    title = (name or code).strip()[:180]
    if Analyte.objects.filter(name__iexact=title).exists():
        title = f"{title} [{code}]"
    return Analyte.objects.create(code=code, name=title, unit=unit[:30])


@transaction.atomic
def ingest(
    device: str,
    analysis: str,
    code_entered: str,
    values: list[IncomingValue],
    message_id: str = "",
    received_at: datetime | None = None,
) -> LabResult:
    """Принять результат с прибора: найти запись медкарты по номеру для анализатора
    (или питомца по лабораторному номеру), сохранить показатели с отметками ↑↓.

    Повтор того же сообщения (message_id) не задваивается. Номер не нашёлся —
    результат попадает в «нераспределённые».
    """
    if not values:
        raise LabError("В результате нет ни одного показателя.")
    if message_id:
        existing = LabResult.objects.filter(message_id=message_id).first()
        if existing is not None:
            return existing
    visit = medical.visit_by_lab_code(code_entered)
    pet = visit.pet if visit else clients.pet_by_lab_number(code_entered)
    result = LabResult.objects.create(
        visit=visit,
        pet=pet,
        device=device[:100],
        analysis=(analysis or device)[:200],
        code_entered=str(code_entered or "")[:50],
        received_at=received_at or timezone.now(),
        status=LabResult.Status.ASSIGNED if pet else LabResult.Status.UNASSIGNED,
        message_id=message_id[:100],
    )
    _save_values(result, values)
    return result


def _save_values(result: LabResult, values: list[IncomingValue]) -> None:
    species_id = result.pet.species_id if result.pet else None
    rows = []
    for position, v in enumerate(values):
        analyte = _analyte(v.get("code", ""), v.get("name", ""), v.get("unit", ""))
        norm = analyte.norms.filter(species_id=species_id).first() if species_id else None
        value = str(v.get("value", "")).strip()[:100]
        rows.append(
            LabValue(
                result=result,
                analyte=analyte,
                name=analyte.name,
                value=value,
                numeric=numeric(value),
                unit=(v.get("unit") or analyte.unit)[:30],
                reference=str(v.get("reference") or "")[:60],
                flag=flag_of(value, v.get("reference", ""), v.get("flag", ""), norm),
                position=position,
            )
        )
    LabValue.objects.bulk_create(rows)


@transaction.atomic
def assign(result: LabResult, visit: Any) -> LabResult:
    """Привязать нераспределённый (или ошибочно привязанный) результат к записи медкарты."""
    result.visit = visit
    result.pet = visit.pet
    result.status = LabResult.Status.ASSIGNED
    result.save(update_fields=["visit", "pet", "status"])
    # Отметки по нормам вида пересчитываются: теперь вид животного известен.
    for v in result.values.select_related("analyte"):
        norm = (
            v.analyte.norms.filter(species_id=visit.pet.species_id).first() if v.analyte else None
        )
        new = flag_of(v.value, v.reference, "", norm) if not v.flag or v.flag == F.NONE else v.flag
        if new != v.flag:
            v.flag = new
            v.save(update_fields=["flag"])
    return result


# --- Выборки ------------------------------------------------------------------------


def results(visit: Any = None, pet: Any = None, status: str | None = None) -> QuerySet[LabResult]:
    queryset = LabResult.objects.prefetch_related("values").select_related("pet", "visit")
    if visit is not None:
        queryset = queryset.filter(visit=visit)
    if pet is not None:
        queryset = queryset.filter(pet=pet)
    if status:
        queryset = queryset.filter(status=status)
    return queryset


def history(pet: Any, analyte: Any) -> list[dict[str, Any]]:
    """Динамика показателя у питомца: дата, значение, отметка — по возрастанию даты."""
    rows = (
        LabValue.objects.filter(result__pet=pet, analyte=analyte)
        .select_related("result")
        .order_by("result__received_at")
    )
    return [
        {
            "date": r.result.received_at,
            "value": r.value,
            "numeric": r.numeric,
            "unit": r.unit,
            "reference": r.reference,
            "flag": r.flag,
        }
        for r in rows
    ]


def unassigned_count() -> int:
    return LabResult.objects.filter(status=LabResult.Status.UNASSIGNED).count()
