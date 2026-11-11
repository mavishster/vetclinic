"""Перенос из VetManager: публичный вход модуля.

Отвечает за: перенос справочников, товаров и услуг, клиентов, питомцев, медкарт и счетов.
Переносим по шагам и повторяемо: уже перенесённое не задваивается (таблица Imported).

Бизнес-правила живут здесь, а не в моделях и не в API (ENGINEERING.md).
"""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction

from catalog import services as catalog
from catalog.models import Item, ItemGroup, ItemUnit, Kind, Unit
from vetmanager import client
from vetmanager.models import Imported

VetManagerError = client.VetManagerError

# Шаги переноса — по порядку: каждый следующий опирается на предыдущие.
STEPS = [
    ("units", "Единицы измерения"),
    ("item_groups", "Группы прайса"),
    ("items", "Товары и услуги"),
]


@dataclass
class StepResult:
    step: str
    title: str
    total: int = 0  # записей в VetManager
    created: int = 0
    updated: int = 0
    skipped: int = 0  # уже переносили
    errors: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        parts = [f"всего {self.total}", f"добавлено {self.created}"]
        if self.updated:
            parts.append(f"обновлено {self.updated}")
        if self.skipped:
            parts.append(f"уже было {self.skipped}")
        if self.errors:
            parts.append(f"с ошибками {len(self.errors)}")
        return ", ".join(parts)


def _text(row: dict[str, Any], *names: str) -> str:
    """Значение по первому попавшемуся имени поля: у разных версий API они разные."""
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _link(kind: str, external_id: str) -> Imported | None:
    return Imported.objects.filter(kind=kind, external_id=str(external_id)).first()


def _remember(kind: str, external_id: str, target_id: Any) -> None:
    Imported.objects.update_or_create(
        kind=kind, external_id=str(external_id), defaults={"target_id": target_id}
    )


def imported_count(kind: str) -> int:
    return Imported.objects.filter(kind=kind).count()


# --- Шаги -----------------------------------------------------------------------------


@transaction.atomic
def import_units(rows: list[dict[str, Any]] | None = None) -> StepResult:
    """Единицы измерения VetManager → наш справочник единиц."""
    rows = client.fetch("Unit") if rows is None else rows
    result = StepResult("units", "Единицы измерения", total=len(rows))
    for row in rows:
        name = _text(row, "title", "name")
        if not name:
            result.errors.append(f"Единица {row.get('id')}: нет названия.")
            continue
        if _link("unit", row["id"]):
            result.skipped += 1
            continue
        unit = Unit.objects.filter(name__iexact=name).first()
        if unit is None:
            unit = Unit.objects.create(name=name)
            result.created += 1
        else:
            result.updated += 1
        _remember("unit", row["id"], unit.pk)
    return result


@transaction.atomic
def import_item_groups(rows: list[dict[str, Any]] | None = None) -> StepResult:
    """Группы товаров VetManager → группы прайса.

    Вложенность разворачивается в название «Родитель / Группа».
    """
    rows = client.fetch("GoodGroup") if rows is None else rows
    result = StepResult("item_groups", "Группы прайса", total=len(rows))
    titles = {str(row["id"]): _text(row, "title", "name") for row in rows if row.get("id")}
    parents = {str(row["id"]): str(row.get("parent_id") or "") for row in rows if row.get("id")}

    def full_name(external_id: str, depth: int = 0) -> str:
        own = titles.get(external_id, "")
        parent = parents.get(external_id, "")
        if parent and parent in titles and depth < 5:
            return f"{full_name(parent, depth + 1)} / {own}".strip(" /")
        return own

    for row in rows:
        external_id = str(row.get("id") or "")
        name = full_name(external_id)[:150]
        if not name:
            result.errors.append(f"Группа {external_id}: нет названия.")
            continue
        if _link("item_group", external_id):
            result.skipped += 1
            continue
        group = ItemGroup.objects.filter(name__iexact=name).first()
        if group is None:
            group = ItemGroup.objects.create(name=name, kind=Kind.GOODS)
            result.created += 1
        else:
            result.updated += 1
        _remember("item_group", external_id, group.pk)
    return result


def _goods_rows() -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    goods = client.fetch("Good")
    prices: dict[str, list[dict[str, Any]]] = {}
    for row in client.fetch("GoodSaleParam"):
        prices.setdefault(str(row.get("good_id") or ""), []).append(row)
    return goods, prices


@transaction.atomic
def import_items(
    goods: list[dict[str, Any]] | None = None, prices: dict[str, list[dict[str, Any]]] | None = None
) -> StepResult:
    """Товары и услуги VetManager → прайс: позиция, единицы продажи и цены.

    Услугой считается то, что не ведётся по складу (у VetManager — is_warehouse_account = 0).
    Цены берутся из GoodSaleParam: по одной строке на единицу продажи.
    """
    if goods is None or prices is None:
        goods, prices = _goods_rows()
    result = StepResult("items", "Товары и услуги", total=len(goods))
    units_by_external = {
        link.external_id: link.target_id for link in Imported.objects.filter(kind="unit")
    }
    groups_by_external = {
        link.external_id: link.target_id for link in Imported.objects.filter(kind="item_group")
    }
    for row in goods:
        external_id = str(row.get("id") or "")
        name = _text(row, "title", "name")
        if not name:
            result.errors.append(f"Позиция {external_id}: нет названия.")
            continue
        if _link("item", external_id):
            result.skipped += 1
            continue
        tracked = str(row.get("is_warehouse_account", "1")) in ("1", "True", "true")
        kind = Kind.GOODS if tracked else Kind.SERVICE
        group = _group_for(row, groups_by_external, kind)
        base_unit = _unit_for(row.get("unit_storage_id"), units_by_external, kind)
        units = _units_for(prices.get(external_id, []), base_unit, units_by_external)
        item = Item(
            kind=kind,
            name=name[:200],
            group=group,
            base_unit=base_unit,
            article=_text(row, "code", "article")[:50],
            barcode=_text(row, "barcode")[:50],
            stock_tracked=tracked,
            is_active=str(row.get("status", "ACTIVE")).upper() not in ("DELETED", "0", "ARCHIVE"),
        )
        try:
            saved = catalog.save_item(item, units)
        except catalog.CatalogError as error:
            result.errors.append(f"«{name}»: {error}")
            continue
        _remember("item", external_id, saved.pk)
        result.created += 1
    return result


def _group_for(row: dict[str, Any], groups: dict[str, Any], kind: str) -> ItemGroup:
    """Группа нужного вида: у нас группы товаров и услуг раздельные, а в VetManager общие,
    поэтому для услуги заводится группа с тем же названием, но для услуг."""
    group_id = groups.get(str(row.get("group_id") or ""))
    group = ItemGroup.objects.filter(pk=str(group_id)).first() if group_id else None
    if group is not None and group.kind == kind:
        return group
    name = group.name if group is not None else "Без группы (VetManager)"
    same_kind = ItemGroup.objects.filter(name=name, kind=kind).first()
    return same_kind or ItemGroup.objects.create(name=name, kind=kind)


def _unit_for(external_id: Any, units: dict[str, Any], kind: str) -> Unit:
    found = units.get(str(external_id or ""))
    unit = Unit.objects.filter(pk=str(found)).first() if found else None
    if unit is not None:
        return unit
    name = "усл." if kind == Kind.SERVICE else "шт."
    return Unit.objects.filter(name=name).first() or Unit.objects.create(name=name)


def _units_for(
    price_rows: list[dict[str, Any]], base_unit: Unit, units: dict[str, Any]
) -> list[catalog.UnitData]:
    """Единицы продажи с ценами. Нет цен — одна строка по единице учёта без цены."""
    prepared: list[catalog.UnitData] = []
    seen: set[Any] = set()
    for row in price_rows:
        found = units.get(str(row.get("unit_sale_id") or ""))
        unit = (Unit.objects.filter(pk=str(found)).first() if found else None) or base_unit
        if unit.pk in seen:
            continue
        seen.add(unit.pk)
        ratio = _decimal(row.get("coefficient")) or Decimal("1")
        prepared.append(
            {
                "unit": unit.pk,
                "ratio": ratio if unit.pk != base_unit.pk and ratio > 0 else Decimal("1"),
                "pricing": ItemUnit.Pricing.FIXED,
                "price": _decimal(row.get("price")) or Decimal("0"),
                "price_min": _decimal(row.get("min_price")),
                "for_sale": True,
            }
        )
    if not prepared:
        prepared.append(
            {
                "unit": base_unit.pk,
                "ratio": Decimal("1"),
                "pricing": ItemUnit.Pricing.FIXED,
                "price": Decimal("0"),
                "for_sale": True,
            }
        )
    return prepared


def run_step(step: str) -> StepResult:
    """Выполнить шаг переноса: данные берутся из VetManager по его API."""
    if step == "units":
        return import_units()
    if step == "item_groups":
        return import_item_groups()
    if step == "items":
        return import_items()
    raise VetManagerError(f"Неизвестный шаг переноса: {step}.")


def status() -> list[dict[str, Any]]:
    """Что уже перенесено — для экрана переноса."""
    kinds = {"units": "unit", "item_groups": "item_group", "items": "item"}
    return [
        {"step": step, "title": title, "imported": imported_count(kinds[step])}
        for step, title in STEPS
    ]
