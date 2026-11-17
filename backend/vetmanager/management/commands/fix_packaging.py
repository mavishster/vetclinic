"""Привести упаковку препаратов в порядок по правилам клиники (сначала просмотр).

Правила:
  • «Зоотовары» и вакцины, а также упаковки из одной штуки — продаются целиком:
    позиция помечается «не трогать», розничная единица не нужна;
  • таблетки и капсулы («уп. 15 табл.») — остаток в таблетках, упаковка для закупки;
  • инъекции и растворы по мл (список слов ниже) — остаток в мл, флакон для закупки;
  • остальные жидкости с объёмом (суспензии, капли, спреи) — флаконом целиком;
  • всё, что по названию не понять, только перечисляется — разбирать вручную.

Цена розничной единицы = цена упаковки / количество внутри (проверьте после применения).

    python manage.py fix_packaging            # только показать
    python manage.py fix_packaging --apply    # применить
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.core.management.base import BaseCommand

from catalog.models import Item
from catalog.services import CatalogError
from vetmanager import tidy
from vetmanager.management.commands.audit_drugs import audit

# Растворы и инъекции, которые отпускают по мл (остальные жидкости — флаконом целиком).
BY_ML_WORDS = (
    "новокаин",
    "глюкоз",
    "натрий хлорид",
    "натрия хлорид",
    "гентамицин",
    "кофеин",
    "тилозин",
    "виме-лайт",
    "преднивет",
    "флексопрофен",
    "фортикарб",
    "котэрвин",
    "фенпраз сусп",
)
WHOLE_GROUPS = {"зоотовары"}
WHOLE_WORDS = ("вакцин", "нобивак")
_DOSE_UNITS = {"мг", "г"}  # в названии это дозировка, а не количество в упаковке


@dataclass
class Plan:
    item: Item
    action: str  # "split" — завести розничную единицу, "whole" — не трогать, "ask" — вручную
    quantity: Decimal | None = None
    inside: str = ""
    note: str = ""


def _counts(name: str) -> list[tuple[Decimal, str]]:
    """Количества штучных единиц в названии (без дозировок): «уп. 15 табл.» → [(15, «таб.»)]."""
    found = []
    for amount, word in tidy._INSIDE.findall(name):
        key = word.lower().rstrip(".")
        unit = (
            tidy._INSIDE_UNIT.get(key[:5])
            or tidy._INSIDE_UNIT.get(key[:3])
            or tidy._INSIDE_UNIT.get(key)
        )
        if unit and unit not in _DOSE_UNITS:
            found.append((Decimal(amount.replace(",", ".")), unit))
    return found


def decide(item: Item) -> Plan:
    name = item.name.lower().replace("ё", "е")
    if item.group.name.lower() in WHOLE_GROUPS:
        return Plan(item, "whole", note="зоотовар — продаётся целиком")
    if any(word in name for word in WHOLE_WORDS):
        return Plan(item, "whole", note="вакцина — флакон на одну дозу")
    counts = _counts(item.name)
    if len(set(counts)) != 1 or "№" in name or "*" in name or "лиофилизат" in name:
        return Plan(item, "ask", note="по названию не понять, сколько внутри")
    quantity, inside = counts[0]
    if quantity <= 1:
        return Plan(item, "whole", note="упаковка из одной штуки")
    if inside in {"таб.", "капс."}:
        return Plan(item, "split", quantity, inside, "таблетки — остаток в штуках")
    if inside == "мл":
        if any(word in name for word in BY_ML_WORDS):
            return Plan(item, "split", quantity, inside, "раствор — остаток в мл")
        return Plan(item, "whole", note="суспензия, капли или спрей — флаконом")
    return Plan(item, "ask", note=f"внутри {quantity} {inside} — уточните")


def retail_price(item: Item, quantity: Decimal) -> Decimal | None:
    price = tidy._price(item)
    if price is None:
        return None
    return (price / quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class Command(BaseCommand):
    help = "Привести упаковку препаратов в порядок по правилам клиники (--apply — применить)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--apply", action="store_true", help="применить (иначе показать)")

    def handle(self, *args: Any, **options: Any) -> None:
        plans = [decide(item) for item, _msg in audit()["no_retail"]]
        for title, action in (
            ("Завести розничную единицу", "split"),
            ("Продаются целиком — пометить «не трогать»", "whole"),
            ("Разобрать вручную", "ask"),
        ):
            rows = [p for p in plans if p.action == action]
            self.stdout.write(self.style.WARNING(f"\n{title}: {len(rows)}"))
            for plan in rows:
                extra = ""
                if action == "split" and plan.quantity:
                    price = retail_price(plan.item, plan.quantity)
                    shown = price if price is not None else "не задана"
                    extra = (
                        f" → {plan.quantity} {plan.inside} в упаковке, "
                        f"цена за {plan.inside}: {shown}"
                    )
                self.stdout.write(f"  {plan.item.name}{extra} ({plan.note})")
        if not options["apply"]:
            self.stdout.write("\nЭто предварительный просмотр. Применить: --apply")
            return

        done = marked = 0
        for plan in plans:
            if plan.action == "whole":
                tidy.skip_packaging(str(plan.item.pk))
                marked += 1
            elif plan.action == "split" and plan.quantity:
                try:
                    tidy.set_packaging(
                        str(plan.item.pk),
                        plan.quantity,
                        plan.inside,
                        retail_price(plan.item, plan.quantity),
                    )
                    done += 1
                except CatalogError as error:
                    self.stdout.write(self.style.ERROR(f"  не удалось: {error}"))
        self.stdout.write(
            self.style.SUCCESS(
                f"\nПереведено на розничную единицу: {done}, помечено «не трогать»: {marked}"
            )
        )
