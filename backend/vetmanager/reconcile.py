"""Сверка переноса: сколько записей в VetManager, сколько у нас и чего не хватает.

Экран сверки отвечает на один вопрос: ничего ли не потерялось. По каждому разделу
считаем записи с обеих сторон и показываем поимённо, что не доехало и почему.
"""

from collections import Counter
from typing import Any

from catalog.models import Item
from clients.models import Client, Pet
from core.models import User
from medical.models import Visit
from vetmanager import client as api
from vetmanager.models import Imported

# Раздел сверки: что считаем у них, что у нас и как это назвать.
SECTIONS: list[tuple[str, str, str]] = [
    ("items", "Товары и услуги", "Good"),
    ("clients", "Клиенты", "Client"),
    ("pets", "Питомцы", "Pet"),
    ("visits", "Медкарты", "MedicalCards"),
    ("invoices", "Счета", "invoice"),
    ("invoice_lines", "Строки счетов", "invoiceDocument"),
]

# Раздел → что хранится у нас и под каким именем записана связь переноса.
MODELS: dict[str, tuple[Any, str]] = {
    "items": (Item, "item"),
    "clients": (Client, "client"),
    "pets": (Pet, "pet"),
    "visits": (Visit, "visit"),
    "doctors": (User, "doctor"),
}


def _alive(kind: str) -> set[str]:
    """Что действительно живо у нас по связям переноса этого раздела.

    Связь на удалённую запись перенесённой не считается: именно так теряются
    строки счетов после объединения позиций.
    """
    found = MODELS.get(kind)
    if found is None:
        return set()
    model, link_kind = found
    targets = {
        str(link.target_id): link.external_id for link in Imported.objects.filter(kind=link_kind)
    }
    live = {str(pk) for pk in model.objects.values_list("pk", flat=True)}
    return {external for target, external in targets.items() if target in live}


def _rows(model: str) -> list[dict[str, Any]] | None:
    try:
        return api.fetch(model)
    except api.VetManagerError:
        return None


def items_section() -> dict[str, Any]:
    """Прайс: позиции VetManager против наших, с учётом объединённых."""
    rows = _rows("Good")
    if rows is None:
        return {"error": "Нет связи с VetManager"}
    names = {str(row.get("id")): str(row.get("title") or "") for row in rows}
    linked = _alive("items")
    missing = [
        {"id": external, "name": names[external], "reason": "не перенеслась"}
        for external in names
        if external not in linked
    ]
    return {"theirs": len(names), "ours": len(linked), "missing": missing}


def invoice_lines_section() -> dict[str, Any]:
    """Строки счетов: на что сошлются при переносе и сколько строк потеряется."""
    rows = _rows("invoiceDocument")
    if rows is None:
        return {"error": "Нет связи с VetManager"}
    used = Counter(str(row.get("good_id") or "") for row in rows)
    used.pop("", None)
    goods = _rows("Good") or []
    names = {str(row.get("id")): str(row.get("title") or "") for row in goods}
    linked = _alive("items")
    missing = [
        {
            "id": external,
            "name": names.get(external, ""),
            "lines": count,
            "reason": (
                "позиция не перенеслась"
                if external in names
                else "позиция удалена в самом VetManager"
            ),
        }
        for external, count in used.items()
        if external not in linked
    ]
    missing.sort(key=lambda row: -row["lines"])
    lost = sum(row["lines"] for row in missing)
    return {
        "theirs": len(rows),
        "ours": len(rows) - lost,
        "missing": missing,
        "note": f"потеряется строк: {lost}" if lost else "",
    }


def simple_section(kind: str, model: str) -> dict[str, Any]:
    """Клиенты, питомцы, медкарты, счета: сколько там и сколько доехало."""
    rows = _rows(model)
    if rows is None:
        return {"error": "Нет связи с VetManager"}
    linked = _alive(kind)
    return {"theirs": len(rows), "ours": len(linked), "missing": []}


def report() -> list[dict[str, Any]]:
    """Сверка по всем разделам — для экрана."""
    found = []
    for key, title, model in SECTIONS:
        if key == "items":
            section = items_section()
        elif key == "invoice_lines":
            section = invoice_lines_section()
        else:
            section = simple_section(key, model)
        theirs, ours = section.get("theirs"), section.get("ours")
        found.append(
            {
                "key": key,
                "title": title,
                "ok": theirs is not None and theirs == ours,
                **section,
            }
        )
    return found
