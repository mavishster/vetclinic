"""Ввод остатков по списку из старого файла склада клиники.

Файл — как у клиники: «Штрикод», «Наиминование», «Дата» (срок годности), «Количество»
(в ней единица: уп, фл), «На складе» (количество), строки-заголовки «Поступление …».
"""

import io
from datetime import date, datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook
from rest_framework.test import APIClient

from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from core import services as core
from inventory import checklist, services
from inventory.models import StockDocument, Warehouse

D = Decimal

HEADER = ("Штрикод ", "Наиминование", "Дата", "Количество", "На складе ", None)
ROWS = [
    (4607145637069, "ЗООКАРД  10 таблеток для собак мелких пород", datetime(2028, 6, 1), "уп", 3),
    (4680015640031, "Фелиферон уп. 5 фл.", datetime(2027, 9, 1), "уп", 2),
    (None, "Цинк оксид адгезивный пластырь", datetime(2026, 5, 19), "шт", 26),
    (None, "Поступление 03.07.2026", None, None, None),
    (4607145633085, "Зоокард суспензия 25мл д/собак мелких пород", "?", "фл", 1),
    (4600000000017, "Совсем незнакомый товар", None, "шт", None),
]


def xlsx(rows) -> bytes:
    workbook = Workbook()
    workbook.active.append(HEADER)
    for row in rows:
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def goods(name, units):
    group = ItemGroup.objects.get(name="Препараты")
    base = Unit.objects.get(name=units[0][0])
    return catalog.save_item(
        Item(kind=Kind.GOODS, name=name, group=group, base_unit=base),
        [
            {"unit": Unit.objects.get(name=unit), "ratio": D(ratio), "price": D(price), **extra}
            for unit, ratio, price, *more in units
            for extra in [more[0] if more else {}]
        ],
    )


@pytest.fixture
def stock(db):
    Unit.objects.get_or_create(name="шт.")
    return {
        "zoocard": goods(
            "Зоокард 10 таблеток для собак мелких пород",
            [("таб.", "1", "60"), ("упак.", "10", "550")],
        ),
        "feliferon": goods(
            "Фелиферон",
            [("фл.", "1", "700"), ("упак.", "5", "3500", {"barcode": "4680015640031"})],
        ),
        "suspension": goods("Зоокард суспензия 25 мл д/собак мелких пород", [("фл.", "1", "900")]),
        "plaster": goods("Цинк оксид адгезивный пластырь", [("шт.", "1", "40")]),
    }


@pytest.fixture
def api(db):
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    return client


def draft():
    return services.save_document(
        StockDocument(kind="inventory", warehouse=Warehouse.objects.get(name="Основной склад"))
    )


def by_name(rows):
    return {row["name"]: row for row in rows}


def test_parse_reads_clinic_file_and_matches(stock) -> None:
    rows = by_name(checklist.parse(xlsx(ROWS), "Склад.xlsx"))

    assert "Поступление 03.07.2026" not in rows  # заголовок раздела, не товар
    zoocard = rows["ЗООКАРД  10 таблеток для собак мелких пород"]
    # По названию (регистр и двойной пробел не мешают), единица «уп» → упаковка.
    assert (zoocard["match"], zoocard["unit_name"], zoocard["ratio"]) == ("name", "упак.", "10")
    assert (zoocard["qty_file"], zoocard["expiry"], zoocard["barcode"]) == (
        "3",
        "2028-06-01",
        "4607145637069",
    )
    feliferon = rows["Фелиферон уп. 5 фл."]
    assert (feliferon["match"], feliferon["item_name"]) == ("barcode", "Фелиферон")
    assert rows["Цинк оксид адгезивный пластырь"]["unit_name"] == "шт."
    suspension = rows["Зоокард суспензия 25мл д/собак мелких пород"]
    assert suspension["match"] in ("name", "similar") and suspension["expiry"] is None
    assert suspension["section"] == "Поступление 03.07.2026"
    unknown = rows["Совсем незнакомый товар"]
    assert (unknown["match"], unknown["item_unit"], unknown["qty_file"]) == ("", None, None)
    assert checklist.summary(list(rows.values()))["missing"] == 1


def test_similar_name_is_only_a_suggestion(stock) -> None:
    rows = checklist.parse(
        xlsx([(None, "Зоокард 10 таблеток д/собак мелких пород", None, "уп", 1)]), "f.xlsx"
    )

    assert rows[0]["match"] == "similar"
    assert rows[0]["candidates"][0]["item_name"] == "Зоокард 10 таблеток для собак мелких пород"


def test_upload_tick_and_execute_through_api(stock, api) -> None:
    document = draft()
    upload = SimpleUploadedFile("Склад_2_11_08_2026.xlsx", xlsx(ROWS))

    loaded = api.post(
        f"/api/inventory/documents/{document.pk}/checklist/", {"file": upload}, format="multipart"
    ).json()

    assert loaded["checklist_name"] == "Склад_2_11_08_2026.xlsx"
    assert loaded["checklist_summary"]["total"] == 5
    zoocard = by_name(loaded["checklist"])["ЗООКАРД  10 таблеток для собак мелких пород"]
    # На полке нашли 2 упаковки вместо 3 по файлу — строка документа помнит строку файла.
    body = {
        "lines": [
            {
                "item_unit": zoocard["item_unit"],
                "quantity": "2",
                "expiry_date": zoocard["expiry"],
                "checklist_row": zoocard["row"],
            }
        ]
    }
    saved = api.patch(f"/api/inventory/documents/{document.pk}/", body, format="json").json()
    assert saved["lines"][0]["checklist_row"] == zoocard["row"]
    assert len(saved["checklist"]) == 5  # список хранится с черновиком

    assert api.post(f"/api/inventory/documents/{document.pk}/execute/").status_code == 200
    assert services.available(stock["zoocard"]) == D("20")  # 2 упаковки по 10 таблеток
    batch = services.batch_stock(stock["zoocard"])[0]
    assert batch.batch.expiry_date == date(2028, 6, 1)


def test_save_barcodes_to_catalog(stock, api) -> None:
    document = draft()
    api.post(
        f"/api/inventory/documents/{document.pk}/checklist/",
        {"file": SimpleUploadedFile("f.xlsx", xlsx(ROWS))},
        format="multipart",
    )

    result = api.post(f"/api/inventory/documents/{document.pk}/checklist_barcodes/").json()

    pack = stock["zoocard"].units.get(unit__name="упак.")
    assert catalog.find_by_barcode("4607145637069").pk == pack.pk  # теперь находится сканером
    assert result["saved"] >= 1
    zoocard = by_name(result["checklist"])["ЗООКАРД  10 таблеток для собак мелких пород"]
    assert zoocard["match"] == "barcode"
    # Чужой штрихкод не перезаписывает свой и не уводит код у другой позиции.
    assert stock["feliferon"].units.get(unit__name="упак.").barcode == "4680015640031"


def test_save_barcodes_skips_code_taken_by_other_item(stock) -> None:
    document = draft()
    checklist.load(
        document,
        xlsx([(4680015640031, "Цинк оксид адгезивный пластырь", None, "шт", 1)]),
        "f.xlsx",
    )
    document.checklist[0]["match"] = "manual"  # выбрали вручную, штрихкод — Фелиферона
    document.checklist[0]["item_unit"] = str(stock["plaster"].units.get().pk)
    document.save(update_fields=["checklist"])

    result = checklist.save_barcodes(document)

    assert result["saved"] == 0 and "Фелиферон" in result["skipped"][0]
    assert stock["plaster"].units.get().barcode == ""


def test_checklist_only_for_inventory_draft(stock) -> None:
    receipt = services.save_document(
        StockDocument(kind="receipt", warehouse=Warehouse.objects.get(name="Основной склад"))
    )

    with pytest.raises(checklist.ChecklistError):
        checklist.load(receipt, xlsx(ROWS), "f.xlsx")


def test_lookup_reads_gs1_datamatrix(stock, api) -> None:
    """DataMatrix с упаковки: GTIN → штрихкод, срок и серия — для строки документа."""
    code = "(01)04680015640031(17)270930(10)FEL-77"

    found = api.get("/api/inventory/stock/lookup/", {"barcode": code}).json()

    assert found[0]["item_name"] == "Фелиферон" and found[0]["unit_name"] == "упак."
    assert (found[0]["scanned_expiry"], found[0]["scanned_series"]) == ("2027-09-30", "FEL-77")


def test_execute_without_price_keeps_zero_cost(stock) -> None:
    """Цен остатков пока нет — партия с нулевой себестоимостью, цену внесут позже."""
    document = draft()
    pack = stock["zoocard"].units.get(unit__name="упак.")
    services.save_document(document, [{"item_unit": pack, "quantity": D("1")}])

    core.execute_document(document)

    assert services.batch_stock(stock["zoocard"])[0].batch.cost_per_base == 0
