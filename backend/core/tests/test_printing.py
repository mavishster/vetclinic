"""Печатные формы: фильтры, песочница, HTML и PDF."""

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model

from core import printing, services
from core.context import acting_user
from core.models import PrintTemplate
from core.printing import PrintTemplateError, render_html

NBSP = "\u00a0"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("1234.5"), f"1{NBSP}234,50{NBSP}₽"),
        (Decimal("1234567.891"), f"1{NBSP}234{NBSP}567,89{NBSP}₽"),
        (0, f"0,00{NBSP}₽"),
        (Decimal("-50"), f"−50,00{NBSP}₽"),
        (None, ""),
    ],
)
def test_money_filter(value, expected) -> None:
    assert printing.money(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(Decimal("1.500"), "1,5"), (Decimal("2.000"), "2"), (Decimal("10"), "10"), (None, "")],
)
def test_qty_filter(value, expected) -> None:
    assert printing.qty(value) == expected


def test_date_filters_use_local_time(settings) -> None:
    settings.TIME_ZONE = "Europe/Moscow"
    moment = datetime(2026, 10, 28, 21, 30, tzinfo=ZoneInfo("UTC"))

    assert printing.format_date(date(2026, 1, 5)) == "05.01.2026"
    assert printing.format_date(moment) == "29.10.2026"
    assert printing.format_datetime(moment) == "29.10.2026 00:30"
    assert printing.format_date(None) == ""


def test_fragment_is_wrapped_into_page_with_default_styles() -> None:
    html = render_html("<p>{{ clinic.name }}</p>", {"clinic": {"name": "Айболит"}})

    assert html.startswith("<!doctype html>")
    assert "@page" in html
    assert "<p>Айболит</p>" in html


def test_full_page_template_is_kept_as_is() -> None:
    body = "<html><body>своя страница</body></html>"

    assert render_html(body, {}) == body


def test_unknown_variables_render_empty() -> None:
    assert "<p></p>" in render_html("<p>{{ client.pet.name }}</p>", {})


def test_values_are_escaped() -> None:
    html = render_html("{{ name }}", {"name": "<script>alert(1)</script>"})

    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_syntax_error_reports_line() -> None:
    with pytest.raises(PrintTemplateError, match="строка 2"):
        render_html("<p>ok</p>\n{{ clinic.name ", {})


def test_sandbox_blocks_unsafe_access() -> None:
    with pytest.raises(PrintTemplateError):
        render_html("{{ ''.__class__.__mro__[1].__subclasses__() }}", {})


def test_pdf_is_produced() -> None:
    assert printing.render_pdf("<h1>Справка</h1>", {}).startswith(b"%PDF")


def test_unknown_kind_is_reported() -> None:
    with pytest.raises(PrintTemplateError, match="Неизвестный вид"):
        printing.get_kind("nope")


@pytest.mark.django_db
def test_common_context_has_clinic_and_user() -> None:
    user = get_user_model().objects.create_user(
        username="u", password="x", last_name="Иванова", first_name="Анна"
    )

    with acting_user(user):
        context = services.common_print_context()

    assert context["clinic"]["name"] == "Клиника"
    assert context["user"]["short_name"] == "Иванова А."
    assert isinstance(context["today"], date)


@pytest.mark.django_db
def test_sample_template_from_migration_renders() -> None:
    template = PrintTemplate.objects.get(kind="general")

    html = services.render_print_sample(template, as_pdf=False)

    assert "Пример печатной формы" in html
    assert f"1{NBSP}234,50{NBSP}₽" in html


@pytest.mark.django_db
def test_render_print_adds_document_data() -> None:
    template = PrintTemplate.objects.create(kind="general", name="Справка", body="{{ pet }}")

    assert services.render_print(template, {"pet": "Барсик"}).startswith(b"%PDF")


@pytest.mark.django_db
def test_invalid_template_fails_model_validation() -> None:
    template = PrintTemplate(kind="general", name="Сломанная", body="{% if %}")

    with pytest.raises(Exception, match="Ошибка в шаблоне"):
        template.full_clean()
