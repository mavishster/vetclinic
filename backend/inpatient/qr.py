"""QR-этикетка пациента стационара: что печатать над кодом и как собрать лист.

В коде — только ссылка на карточку госпитализации, без данных о пациенте: потерянная
этикетка ничего не расскажет. Открыть карточку может только тот, у кого есть право.
Какие поля печатать и размеры в мм — настройки клиники (администрирование).
"""

import base64
import io
from collections.abc import Callable, Iterable
from datetime import date
from typing import Any, TypedDict

import segno
from django.utils import timezone

from clients import services as clients
from core import services as core
from inpatient.models import Hospitalization
from medical import services as medical

SHEET_MARGIN_MM = 5  # поля листа А4: принтер не печатает у самого края
A4_MM = (210, 297)
MAX_COPIES = 8
DIAGNOSIS_LIMIT = 160  # длиннее — сокращается, иначе не поместится на этикетке


class LabelField(TypedDict):
    code: str
    label: str


def diagnosis_text(h: Hospitalization) -> str:
    """Диагноз целиком: причина госпитализации, а если её нет — диагнозы приёма-основания."""
    text = " ".join((h.reason or "").split())
    if not text and h.visit_id:
        text = medical.visit_diagnoses(h.visit_id)
    return text


def _diagnosis(h: Hospitalization) -> str:
    text = diagnosis_text(h)
    return text if len(text) <= DIAGNOSIS_LIMIT else text[: DIAGNOSIS_LIMIT - 1].rstrip() + "…"


def cage_card(h: Hospitalization) -> dict[str, str]:
    """Шапка экрана «у клетки»: то, что нужно увидеть, отсканировав QR."""
    return {
        "age": FIELDS["age"][1](h),
        "weight": _weight(h),
        "species_breed": FIELDS["species_breed"][1](h),
        "diagnosis": diagnosis_text(h),
    }


def _weight(h: Hospitalization) -> str:
    row = clients.current_weight(h.pet)
    return f"{str(row.weight.normalize()).replace('.', ',')} кг" if row else ""


def _place(h: Hospitalization) -> str:
    return f"{h.ward.name}, место {h.place}" if h.place else h.ward.name


# Код поля → (название в настройках, как получить значение). Порядок — порядок по умолчанию.
FIELDS: dict[str, tuple[str, Callable[[Hospitalization], str]]] = {
    "pet_name": ("Кличка", lambda h: h.pet.name),
    "age": ("Возраст", lambda h: medical.age_text(h.pet)),
    "diagnosis": ("Диагноз", _diagnosis),
    "species_breed": (
        "Вид и порода",
        lambda h: ", ".join(p for p in (h.pet.species.name, h.pet.breed.name) if p),
    ),
    "sex": ("Пол", lambda h: h.pet.get_sex_display() if h.pet.sex != "unknown" else ""),
    "weight": ("Вес", _weight),
    "ward_place": ("Палата и место", _place),
    "admitted": ("Поступил", lambda h: f"{timezone.localtime(h.admitted_at):%d.%m.%Y}"),
    "doctor": ("Лечащий врач", lambda h: h.doctor.short_name or h.doctor.username),
    "day": ("Стационар", lambda h: f"{_days(h)}-е сутки"),
    "owner": ("Владелец", lambda h: h.client.full_name),
}


def _days(h: Hospitalization) -> int:
    from inpatient import services

    return services.days_count(h)


def available_fields() -> list[LabelField]:
    return [{"code": code, "label": label} for code, (label, _) in FIELDS.items()]


def card_url(h: Hospitalization, base_url: str) -> str:
    return f"{base_url.rstrip('/')}/inpatient/{h.pk}"


def qr_data_uri(url: str) -> str:
    """QR-код ссылки картинкой для печатной формы (SVG; размер задаёт шаблон)."""
    buffer = io.BytesIO()
    segno.make(url, error="m").save(
        buffer, kind="svg", xmldecl=False, svgns=True, border=0, scale=1, nl=False
    )
    return "data:image/svg+xml;base64," + base64.b64encode(buffer.getvalue()).decode()


def label_for(h: Hospitalization, codes: Iterable[str], base_url: str) -> dict[str, Any]:
    """Одна этикетка: выбранные поля (пустые не выводятся) и QR-код."""
    fields = []
    for code in codes:
        if code not in FIELDS:
            continue  # поле убрали из системы — настройка не ломает печать
        label, getter = FIELDS[code]
        if value := getter(h):
            fields.append({"code": code, "label": label, "value": value})
    url = card_url(h, base_url)
    return {"fields": fields, "url": url, "qr": qr_data_uri(url)}


def layout(width_mm: int, height_mm: int) -> dict[str, int]:
    """Сколько этикеток помещается на листе А4: по ширине и высоте с полями листа."""
    usable_w, usable_h = (side - 2 * SHEET_MARGIN_MM for side in A4_MM)
    cols, rows = max(usable_w // width_mm, 1), max(usable_h // height_mm, 1)
    return {"cols": cols, "rows": rows, "per_sheet": cols * rows}


def sheet_context(
    hospitalizations: Iterable[tuple[Hospitalization, int]], base_url: str
) -> dict[str, Any]:
    """Данные печатной формы: этикетки (с копиями), разложенные по листам А4."""
    clinic = core.current_clinic()
    grid = layout(clinic.qr_label_width_mm, clinic.qr_label_height_mm)
    labels: list[dict[str, Any]] = []
    for h, copies in hospitalizations:
        label = label_for(h, clinic.qr_fields or [], base_url or clinic.qr_base_url)
        labels += [label] * max(1, min(copies, MAX_COPIES))
    per_sheet = grid["per_sheet"]
    return {
        "size": {
            "qr": clinic.qr_size_mm,
            "label_w": clinic.qr_label_width_mm,
            "label_h": clinic.qr_label_height_mm,
            **grid,
        },
        "labels": labels,
        "sheets": [labels[i : i + per_sheet] for i in range(0, len(labels), per_sheet)],
        "today": date.today(),
    }


# Примеры значений для предпросмотра в редакторе печатных форм.
SAMPLE_VALUES = {
    "pet_name": "Барсик",
    "age": "3 года 2 мес.",
    "diagnosis": "Гастроэнтерит",
    "species_breed": "Кошки, Метис",
    "sex": "кот",
    "weight": "4,2 кг",
    "ward_place": "Палата 1, место 2",
    "admitted": date.today().strftime("%d.%m.%Y"),
    "doctor": "Иванова А.",
    "day": "2-е сутки",
    "owner": "Петров Пётр Петрович",
}


def sample_context() -> dict[str, Any]:
    """Пример для редактора печатных форм: поля — те, что выбраны в настройках клиники."""
    url = "http://192.168.0.10/inpatient/00000000-0000-0000-0000-000000000000"
    clinic = core.current_clinic()
    grid = layout(clinic.qr_label_width_mm, clinic.qr_label_height_mm)
    label = {
        "fields": [
            {"code": code, "label": FIELDS[code][0], "value": SAMPLE_VALUES[code]}
            for code in clinic.qr_fields or []
            if code in FIELDS
        ],
        "url": url,
        "qr": qr_data_uri(url),
    }
    return {
        "size": {
            "qr": clinic.qr_size_mm,
            "label_w": clinic.qr_label_width_mm,
            "label_h": clinic.qr_label_height_mm,
            **grid,
        },
        "labels": [label],
        "sheets": [[label]],
        "today": date.today(),
    }
