"""Печатные формы (PROJECT_PLAN 6.1): шаблоны с переменными → HTML → PDF.

Шаблоны редактирует клиника, поэтому они выполняются в песочнице Jinja2:
из шаблона нельзя вызвать опасный код. В шаблон передаются только словари
с данными, а не объекты базы.

Модуль регистрирует свой вид печатной формы — какие переменные доступны
и пример данных для предпросмотра:

    register_kind("invoice", "Счёт", variables={...}, sample=lambda: {...})

Во всех формах доступны общие переменные: clinic, user, today, now.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.utils import timezone
from jinja2 import ChainableUndefined, TemplateError
from jinja2.sandbox import ImmutableSandboxedEnvironment
from weasyprint import HTML

NBSP = "\u00a0"

COMMON_VARIABLES = {
    "clinic.name": "Название клиники",
    "clinic.address": "Адрес клиники",
    "clinic.phone": "Телефон клиники",
    "clinic.logo": (
        "Логотип клиники (Настройки клиники). Вставка: "
        '{% if clinic.logo %}<img src="{{ clinic.logo }}" style="height:18mm">{% endif %}'
    ),
    "user.full_name": "ФИО сотрудника, который печатает",
    "user.short_name": "Фамилия и инициалы сотрудника",
    "today": "Сегодняшняя дата (с фильтром date: {{ today|date }})",
    "now": "Текущие дата и время (с фильтром datetime)",
}

FILTERS_HELP = {
    "money": "Деньги: {{ 1234.5|money }} → 1 234,50 сом",
    "qty": "Количество без лишних нулей: {{ 1.500|qty }} → 1,5",
    "date": "Дата: {{ today|date }} → 28.10.2026",
    "datetime": "Дата и время: {{ now|datetime }} → 28.10.2026 14:30",
}

DEFAULT_CSS = """
@page { size: A4; margin: 15mm; }
body { font-family: 'DejaVu Sans', sans-serif; font-size: 11pt; line-height: 1.4; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #999; padding: 4px 6px; text-align: left; vertical-align: top; }
"""


class PrintTemplateError(Exception):
    """Ошибка в шаблоне. Текст — для того, кто редактирует шаблон."""


@dataclass(frozen=True)
class PrintKind:
    code: str
    title: str
    variables: dict[str, str] = field(default_factory=dict)
    sample: Callable[[], dict[str, Any]] = dict


_KINDS: dict[str, PrintKind] = {}


def register_kind(
    code: str,
    title: str,
    variables: dict[str, str] | None = None,
    sample: Callable[[], dict[str, Any]] = dict,
) -> None:
    _KINDS[code] = PrintKind(code, title, variables or {}, sample)


def kinds() -> list[PrintKind]:
    return sorted(_KINDS.values(), key=lambda kind: kind.title)


def get_kind(code: str) -> PrintKind:
    try:
        return _KINDS[code]
    except KeyError:
        raise PrintTemplateError(f"Неизвестный вид печатной формы: {code}") from None


# --- Фильтры -----------------------------------------------------------------------


def _group_thousands(integer_part: str) -> str:
    groups: list[str] = []
    while integer_part:
        groups.insert(0, integer_part[-3:])
        integer_part = integer_part[:-3]
    return NBSP.join(groups)


def money(value: Any) -> str:
    if value in (None, ""):
        return ""
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    sign = "−" if amount < 0 else ""
    integer, fraction = f"{abs(amount):.2f}".split(".")
    from django.conf import settings

    return f"{sign}{_group_thousands(integer)},{fraction}{NBSP}{settings.CURRENCY}"


def qty(value: Any) -> str:
    if value in (None, ""):
        return ""
    text = format(Decimal(str(value)).normalize(), "f")
    return text.replace(".", ",")


def format_date(value: Any) -> str:
    if isinstance(value, datetime):
        value = timezone.localtime(value) if timezone.is_aware(value) else value
    return value.strftime("%d.%m.%Y") if isinstance(value, date) else ""


def format_datetime(value: Any) -> str:
    if not isinstance(value, datetime):
        return format_date(value)
    local = timezone.localtime(value) if timezone.is_aware(value) else value
    return local.strftime("%d.%m.%Y %H:%M")


_env = ImmutableSandboxedEnvironment(autoescape=True, undefined=ChainableUndefined)
_env.filters.update(money=money, qty=qty, date=format_date, datetime=format_datetime)


# --- Отрисовка ---------------------------------------------------------------------


def render_html(body: str, context: dict[str, Any]) -> str:
    """Шаблон + данные → HTML-страница. Неизвестные переменные выводятся пустыми."""
    try:
        content = _env.from_string(body).render(context)
    except TemplateError as error:
        lineno = getattr(error, "lineno", None)
        line = f" (строка {lineno})" if lineno else ""
        raise PrintTemplateError(f"Ошибка в шаблоне{line}: {error.message}") from error
    if "<html" in content.lower():
        return content
    return (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        f"<style>{DEFAULT_CSS}</style></head><body>{content}</body></html>"
    )


def render_pdf(body: str, context: dict[str, Any]) -> bytes:
    """Шаблон + данные → PDF."""
    pdf: bytes = HTML(string=render_html(body, context)).write_pdf()
    return pdf


def validate(body: str, kind_code: str, common: dict[str, Any]) -> None:
    """Проверить шаблон на примере данных: синтаксис и ошибки при выводе."""
    render_html(body, {**common, **get_kind(kind_code).sample()})


def html_to_pdf(html: str) -> bytes:
    """Готовая HTML-страница → PDF (без шаблонизатора — например, подписанный документ)."""
    pdf: bytes = HTML(string=html).write_pdf()
    return pdf
