"""Проставить действующее вещество и группу препарата по названию позиции.

Вещество ищется в названии: по справочнику действующих веществ (с синонимами и
латинскими названиями) и по словарю торговых названий. Что не распозналось —
выводится отдельным списком, такие позиции заполняет врач.

    python manage.py fill_drug_info              # только показать, что получится
    python manage.py fill_drug_info --apply      # записать
"""

import re
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog import services
from catalog.models import Item, Kind, Substance

# Торговые названия → действующее вещество. Берём только те, где сомнений нет;
# остальное врач проставит сам.
BRANDS = {
    "азинокс": "празиквантел",
    "альбен": "альбендазол",
    "амоксиклав": "амоксициллин",
    "анальгин": "метамизол натрия",
    "анестофол": "пропофол",
    "апомед": "апоморфин",
    "баралгин": "метамизол натрия",
    "бравекто": "флураланер",
    "веракол": "гомеопатия",
    "веткокцин": "толтразурил",
    "вазосан": "пимобендан",
    "авекардит": "пимобендан",
    "гептрал": "адеметионин",
    "адеметионин": "адеметионин",
    "ветгаба": "габапентин",
    "дексафорт": "дексаметазон",
    "дицинон": "этамзилат",
    "катозал": "бутафосфан",
    "квадрисол": "ведапрофен",
    "кетофен": "кетопрофен",
    "локсиком": "мелоксикам",
    "мелоксидил": "мелоксикам",
    "метрогил": "метронидазол",
    "но-шпа": "дротаверин",
    "ношпа": "дротаверин",
    "онсиор": "робенакоксиб",
    "превикокс": "фирококсиб",
    "преднивет": "преднизолон",
    "ринсулин": "инсулин",
    "римадил": "карпрофен",
    "серения": "маропитант",
    "синулокс": "амоксициллин",
    "супрамил": "празиквантел",
    "травматин": "гомеопатия",
    "фоспасим": "гомеопатия",
    "фуросемид": "фуросемид",
    "церукал": "метоклопрамид",
    "цефтриаксон": "цефтриаксон",
    "энроксил": "энрофлоксацин",
    "энрофлон": "энрофлоксацин",
    # Латиницей — в прайсе названия пишут и так.
    "supramil": "празиквантел",
    "bravecto": "флураланер",
    "simparica": "сароланер",
    "nexgard": "афоксоланер",
    "frontline": "фипронил",
    "advocate": "имидаклоприд",
    "onsior": "робенакоксиб",
    "previcox": "фирококсиб",
    "cerenia": "маропитант",
    "synulox": "амоксициллин",
    "metacam": "мелоксикам",
    "rimadyl": "карпрофен",
}


def _simple(text: str) -> str:
    return re.sub(r"[^a-zа-я0-9 ]+", " ", text.lower().replace("ё", "е"))


def _keys(substance: Substance) -> list[str]:
    """Как вещество может называться в прайсе: само название, латинское, синонимы."""
    parts = [substance.name, substance.latin_name, *substance.synonyms.split(",")]
    return [_simple(part).strip() for part in parts if part and part.strip()]


class Command(BaseCommand):
    help = "Проставить действующее вещество и группу препарата по названию."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--apply", action="store_true", help="записать (иначе только показать)")
        parser.add_argument("--show", type=int, default=40, help="сколько строк показать")

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        by_key: dict[str, Substance] = {}
        for substance in Substance.objects.all():
            for key in _keys(substance):
                by_key.setdefault(key, substance)
        for brand, name in BRANDS.items():
            found = Substance.objects.filter(name__iexact=name).first()
            if found is not None:
                by_key.setdefault(_simple(brand), found)

        # Длинные названия ищем первыми: «аскорбиновая кислота» важнее «кислота».
        keys = sorted(by_key, key=len, reverse=True)
        matched: list[tuple[Item, Substance]] = []
        unknown: list[Item] = []
        for item in Item.objects.filter(kind=Kind.GOODS, is_active=True).prefetch_related(
            "substances"
        ):
            if item.substances.exists():
                continue
            name = f" {_simple(item.name)} "
            found = next((by_key[key] for key in keys if f" {key} " in name or key in name), None)
            (matched.append((item, found)) if found else unknown.append(item))

        for item, substance in matched[: options["show"]]:
            self.stdout.write(f"{item.name} → {substance.name}")
        self.stdout.write(
            self.style.SUCCESS(f"\nраспозналось: {len(matched)}, не распозналось: {len(unknown)}")
        )
        for item in unknown[: options["show"]]:
            self.stdout.write(self.style.WARNING(f"  ? {item.name}"))

        if not options["apply"]:
            self.stdout.write("\nЭто предварительный просмотр. Записать: --apply")
            return
        for item, substance in matched:
            services.set_drug_info(item, [substance], None)  # группа — по веществу
        self.stdout.write(self.style.SUCCESS(f"записано: {len(matched)}"))
