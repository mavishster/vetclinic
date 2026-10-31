"""Этикетки и импорт остатков."""

import io
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook
from rest_framework.test import APIClient

from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from core import services as core
from inventory import importing, labels, services
from inventory.models import StockDocument, Warehouse

D = Decimal


@pytest.fixture
def api(db):
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    return client


@pytest.fixture
def feliferon(db):
    return catalog.save_item(
        Item(kind=Kind.GOODS, name="Фелиферон", article="FEL-5", group=ItemGroup.objects.get(name="Препараты"), base_unit=Unit.objects.get(name="фл.")),
        [{"unit": Unit.objects.get(name="фл."), "price": D("700")},
         {"unit": Unit.objects.get(name="упак."), "ratio": D("5"), "price": D("3500"), "for_purchase": True, "barcode": "4680015640031"}],
    )  # fmt: skip


def xlsx(rows) -> bytes:
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_internal_barcode_is_valid_ean13_and_findable(feliferon) -> None:
    vial = feliferon.units.get(unit__name="фл.")

    code = catalog.ensure_barcode(vial)

    assert code.startswith("20") and len(code) == 13
    assert catalog.ensure_barcode(vial) == code  # второй раз — тот же
    assert catalog.find_by_barcode(code).pk == vial.pk
    assert catalog._ean13_check_digit(code[:12]) == code[-1]


def test_label_context_copies_and_batch(feliferon) -> None:
    pack = feliferon.units.get(unit__name="упак.")
    receipt = services.save_document(
        StockDocument(kind="receipt", warehouse=Warehouse.objects.get(name="Основной склад")),
        [
            {
                "item_unit": pack,
                "quantity": D("2"),
                "price": D("2000"),
                "series": "F-77",
                "expiry_date": date(2027, 6, 1),
            }
        ],
    )
    core.execute_document(receipt)
    batch = receipt.lines.get().batch

    context = labels.label_context([{"item_unit": pack, "copies": 3, "batch": batch.pk}])

    assert len(context["labels"]) == 3
    first = context["labels"][0]
    assert first["barcode"] == "4680015640031" and first["series"] == "F-77"
    assert first["barcode_svg"].startswith("<svg")


def test_labels_pdf_from_document(api, feliferon) -> None:
    warehouse = str(Warehouse.objects.get(name="Основной склад").pk)
    doc = api.post(
        "/api/inventory/documents/",
        {
            "kind": "receipt",
            "warehouse": warehouse,
            "lines": [
                {
                    "item_unit": str(feliferon.units.get(unit__name="фл.").pk),
                    "quantity": "2",
                    "price": "400",
                }
            ],
        },
        format="json",
    ).json()

    response = api.post("/api/inventory/labels/", {"document": doc["id"]}, format="json")

    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_import_preview_matches_by_barcode_article_name(feliferon) -> None:
    content = xlsx([
        ["Остатки на 30.10.2026"],
        ["Наименование", "Артикул", "Штрих-код", "Ед. изм.", "Остаток", "Себестоимость", "Серия", "Годен до"],
        ["что угодно", "", "4680015640031", "", 2, 2000, "F-77", "06.2027"],
        ["", "FEL-5", "", "фл.", 3, 400, "", ""],
        ["Фелиферон", "", "", "", 1, 400, "", "31.12.2027"],
        ["Неизвестный препарат", "", "", "", 1, 10, "", ""],
        ["Фелиферон", "", "", "ампула", 1, 10, "", ""],
        ["Фелиферон", "", "", "", 0, 10, "", ""],
        ["Фелиферон", "", "", "", 1, 10, "", "вчера"],
    ])  # fmt: skip

    result = importing.preview(content, "stock.xlsx")

    assert (result["ready"], result["errors"]) == (3, 4)
    assert [r["unit"] for r in result["rows"][:3]] == ["упак.", "фл.", "фл."]
    errors = [r["error"] for r in result["rows"][3:]]
    assert errors == ["Товар не найден в каталоге.", "У товара нет единицы «ампула».",
                      "Количество должно быть больше нуля.", "Строка 9: не дата: «вчера»"]  # fmt: skip
    assert result["sum"] == "5600.00"  # 2×2000 + 3×400 + 1×400


def test_import_commit_creates_draft_receipt(api, feliferon) -> None:
    content = xlsx([["Штрихкод", "Количество", "Закупочная цена", "Серия", "Срок годности"],
                    ["4680015640031", 2, 2000, "F-77", "30.06.2027"]])  # fmt: skip
    warehouse = str(Warehouse.objects.get(name="Основной склад").pk)

    response = api.post(
        "/api/inventory/import/commit/",
        {"file": SimpleUploadedFile("stock.xlsx", content), "warehouse": warehouse},
        format="multipart",
    )
    document = StockDocument.objects.get(pk=response.json()["document"])
    core.execute_document(document)

    assert document.status == "executed"
    assert services.available(feliferon) == D("10")
    assert services.batch_stock(feliferon)[0].batch.cost_per_base == D("400.00")
    assert services.batch_stock(feliferon)[0].batch.expiry_date == date(2027, 6, 30)


def test_import_template_and_errors(api) -> None:
    assert api.get("/api/inventory/import/template/").status_code == 200
    bad = api.post(
        "/api/inventory/import/preview/",
        {"file": SimpleUploadedFile("x.xlsx", b"x")},
        format="multipart",
    )
    assert "Не удалось открыть" in bad.json()["file"][0]
    no_name = xlsx([["Количество"], [1]])
    with pytest.raises(importing.ImportError_, match="Название"):
        importing.preview(no_name, "x.xlsx")
