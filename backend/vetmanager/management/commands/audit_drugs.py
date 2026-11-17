"""Проверка препаратов: упаковка и розничная единица для счетов и списания (только чтение).

У правильного препарата остаток ведётся в мелкой единице (мл, таб.), упаковка записана
как единица с «сколько внутри» и отмечена для закупки, а розничная единица отмечена
«для продажи» — тогда в счёте 2 мл списывают 2 мл, а не флакон.

    python manage.py audit_drugs                     # сводка и первые строки
    python manage.py audit_drugs --show 200          # больше строк
    python manage.py audit_drugs --csv drugs.csv     # полный список в файл
"""

import csv
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand

from catalog.models import Item, Kind
from vetmanager import tidy

# Что внутри упаковки по названию — только штучные единицы: «г» и «мг» в названии
# чаще всего дозировка («Цефтриаксон 1 г»), а не количество в упаковке.
_COUNTABLE = {"таб.", "капс.", "амп.", "саше", "доза", "шт."}


def _units(item: Item) -> list[Any]:
    return [u for u in item.units.all() if not u.is_deleted]


def _no_retail_unit(item: Item) -> str | None:
    """Остаток в упаковках, а отпускают поштучно — продажа 2 мл спишет весь флакон."""
    if item.base_unit.name in tidy.PACK_UNITS and not (
        {u.unit.name for u in _units(item)} & (tidy.PIECE_UNITS - {item.base_unit.name})
    ):
        quantity, inside = tidy._inside_pack(item.name)
        hint = f"внутри, судя по названию: {quantity} {inside}" if quantity and inside else ""
        return f"учёт в «{item.base_unit.name}», розничной единицы нет. {hint}".strip()
    return None


def _no_pack_record(item: Item) -> str | None:
    """Мелкая единица учёта есть, а упаковки в записи нет — приход придётся вводить штуками."""
    if item.base_unit.name not in tidy.PIECE_UNITS:
        return None
    if any(u.ratio > 1 for u in _units(item)):
        return None
    quantity, inside = tidy._inside_pack(item.name)
    if quantity and quantity > 1 and inside in _COUNTABLE:
        return f"в названии {quantity} {inside}, а единицы «упаковка» у позиции нет"
    return None


def _pack_not_for_purchase(item: Item) -> str | None:
    packs = [u for u in _units(item) if u.ratio > 1]
    if packs and not any(u.for_purchase for u in packs):
        return (
            "есть упаковка ("
            + ", ".join(u.unit.name for u in packs)
            + "), но не отмечена «для закупки»"
        )
    return None


def _cannot_sell(item: Item) -> str | None:
    if not item.for_sale or item.combo_only:
        return None
    units = _units(item)
    if units and not any(u.for_sale for u in units):
        return "ни одна единица не отмечена «для продажи» — в счёт не добавить"
    base = next((u for u in units if u.ratio == Decimal("1")), None)
    if (
        base is not None
        and not base.for_sale
        and item.base_unit.name in tidy.PIECE_UNITS
        and any(u.for_sale and u.ratio > 1 for u in units)
    ):
        return f"продаётся только упаковкой, «{item.base_unit.name}» не отмечена «для продажи»"
    return None


CHECKS: list[tuple[str, str, Callable[[Item], str | None]]] = [
    ("no_retail", "Нет розничной единицы (остаток в упаковках)", _no_retail_unit),
    ("no_pack", "Нет записи упаковки", _no_pack_record),
    ("no_purchase", "Упаковка не отмечена для закупки", _pack_not_for_purchase),
    ("cannot_sell", "Нельзя продать розничной единицей", _cannot_sell),
]


def audit() -> dict[str, list[tuple[Item, str]]]:
    """Позиции с проблемами по каждой проверке. Помеченные «не трогать» пропускаются."""
    skipped = tidy._marked_ok()
    found: dict[str, list[tuple[Item, str]]] = {code: [] for code, _t, _f in CHECKS}
    items = (
        Item.objects.filter(kind=Kind.GOODS, is_active=True, is_template=False)
        .select_related("base_unit", "group")
        .prefetch_related("units__unit")
        .order_by("name")
    )
    for item in items:
        if str(item.pk) in skipped:
            continue
        for code, _title, check in CHECKS:
            if message := check(item):
                found[code].append((item, message))
    return found


class Command(BaseCommand):
    help = "Проверить препараты: упаковка и розничная единица (ничего не меняет)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--show", type=int, default=25, help="строк на проверку")
        parser.add_argument("--csv", default="", help="записать полный список в файл")

    def handle(self, *args: Any, **options: Any) -> None:
        found = audit()
        total = Item.objects.filter(kind=Kind.GOODS, is_active=True, is_template=False).count()
        flagged = {item.pk for rows in found.values() for item, _ in rows}
        self.stdout.write(f"Товаров проверено: {total}; с замечаниями: {len(flagged)}\n")
        for code, title, _check in CHECKS:
            rows = found[code]
            self.stdout.write(self.style.WARNING(f"\n{title}: {len(rows)}"))
            for item, message in rows[: options["show"]]:
                self.stdout.write(f"  {item.name} [{item.group.name}] — {message}")
            if len(rows) > options["show"]:
                self.stdout.write(f"  … ещё {len(rows) - options['show']} (--show или --csv)")
        if options["csv"]:
            with open(options["csv"], "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle, delimiter=";")
                writer.writerow(["проверка", "название", "группа", "единица учёта", "замечание"])
                for code, title, _check in CHECKS:
                    for item, message in found[code]:
                        writer.writerow(
                            [title, item.name, item.group.name, item.base_unit.name, message]
                        )
            self.stdout.write(self.style.SUCCESS(f"\nСписок записан: {options['csv']}"))
