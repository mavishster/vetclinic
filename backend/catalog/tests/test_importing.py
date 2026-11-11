"""Импорт прайса: чтение Excel и CSV, сопоставление, создание и обновление."""

import io
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook, load_workbook
from rest_framework.test import APIClient

from catalog import importing
from catalog.models import Item, ItemGroup, Unit


def xlsx(rows) -> bytes:
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


HEADER = [
    "Наименование",
    "Вид",
    "Категория",
    "Ед. изм.",
    "Цена продажи",
    "Себестоимость",
    "Артикул",
]


@pytest.mark.django_db
def test_preview_changes_nothing_and_reports_actions_and_errors() -> None:
    content = xlsx([
        ["Прайс клиники на 2026 год"],  # строка до заголовков — пропускается
        HEADER,
        ["Первичный приём", "Услуга", "Приём и консультации", "", 900, None, ""],
        ["Нобивак DHPPi", "Товар", "Вакцины", "доза", "1 100,50", 650, 123456],
        ["Без группы", "Товар", "", "шт.", 10, None, ""],
        ["Без цены", "Товар", "Препараты", "шт.", None, None, ""],
        ["Плохая цена", "Товар", "Препараты", "шт.", "дорого", None, ""],
    ])  # fmt: skip

    result = importing.preview(content, "price.xlsx")

    assert (result.created, result.errors) == (2, 3)
    assert [r.error for r in result.rows if r.error] == [
        "Не указана группа.",
        "Не указана цена (или наценка).",
        "Строка 7: не число: «дорого»",  # номер строки в Excel
    ]
    assert not Item.objects.exists()


@pytest.mark.django_db
def test_commit_creates_items_groups_and_units_then_updates_by_article() -> None:
    first = xlsx([HEADER,
                  ["Нобивак DHPPi", "Товар", "Вакцины", "доза", 1100, 650, 123456],
                  ["Шампунь от блох", "Товар", "Новая группа", "флакон", 450, None, ""]])  # fmt: skip

    created = importing.commit(first, "price.xlsx")
    item = Item.objects.get(article="123456")

    assert created.created == 2
    assert item.units.get().price == Decimal("1100.00")
    assert item.manual_cost == Decimal("650.00")
    assert ItemGroup.objects.filter(name="Новая группа", kind="goods").exists()
    assert Unit.objects.filter(name="флакон").exists()

    second = xlsx([HEADER, ["Нобивак DHPPi (новое имя)", "Товар", "Вакцины", "доза", 1200, 650, 123456],
                   ["Шампунь от блох", "Товар", "Новая группа", "флакон", 450, None, ""]])  # fmt: skip
    updated = importing.commit(second, "price.xlsx")

    assert (updated.created, updated.updated, updated.unchanged) == (0, 1, 1)
    item.refresh_from_db()
    assert item.units.get().price == Decimal("1200.00")
    assert Item.objects.count() == 2


@pytest.mark.django_db
def test_csv_in_cp1251_with_semicolons_and_markup() -> None:
    content = "Название;Группа;Наценка, %;Себестоимость\nКорм Purina;Корма;30;100\n".encode(
        "cp1251"
    )

    importing.commit(content, "price.csv")

    unit = Item.objects.get(name="Корм Purina").units.get()
    assert unit.pricing == "markup"
    assert unit.markup_percent == Decimal("30.00")


def test_missing_header_and_broken_file() -> None:
    with pytest.raises(importing.ImportError_, match="заголовков"):
        importing.preview(xlsx([["что-то"], ["ещё"]]), "x.xlsx")
    with pytest.raises(importing.ImportError_, match="Не удалось открыть"):
        importing.preview(b"not excel", "x.xlsx")


def test_template_has_headers_that_import_understands() -> None:
    sheet = load_workbook(io.BytesIO(importing.template())).active
    header = [cell.value for cell in sheet[1]]

    assert importing._header_map(header).keys() >= {"name", "kind", "group", "unit", "price"}


@pytest.mark.django_db
def test_template_imports_cleanly() -> None:
    result = importing.preview(importing.template(), "template.xlsx")

    assert (result.created, result.errors) == (4, 0)


@pytest.mark.django_db
def test_api_preview_commit_and_permissions(django_user_model) -> None:
    admin = APIClient()
    admin.force_authenticate(django_user_model.objects.create_superuser(username="a", password="x"))
    plain = APIClient()
    plain.force_authenticate(django_user_model.objects.create_user(username="u", password="x"))

    def upload():
        return {"file": SimpleUploadedFile("price.xlsx", importing.template())}

    preview = admin.post("/api/catalog/import/preview/", upload(), format="multipart")
    commit = admin.post("/api/catalog/import/commit/", upload(), format="multipart")
    bad = admin.post(
        "/api/catalog/import/preview/",
        {"file": SimpleUploadedFile("x.xlsx", b"x")},
        format="multipart",
    )

    assert preview.json()["created"] == 4
    assert commit.json()["created"] == 4
    assert Item.objects.count() == 4
    # В шаблоне есть пример с действующим веществом — оно проставляется при импорте.
    assert [s.name for s in Item.objects.get(name__startswith="Серения").substances.all()] == [
        "маропитант"
    ]
    assert "Не удалось открыть" in bad.json()["file"][0]
    assert (
        plain.post("/api/catalog/import/preview/", upload(), format="multipart").status_code == 403
    )
    assert admin.get("/api/catalog/import/template/").status_code == 200
