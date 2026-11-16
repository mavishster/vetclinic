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
from catalog.models import DrugGroup, Item, Kind, Substance

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
    # Добавлено по прайсу клиники.
    "азитронит": "азитромицин",
    "антимедин": "атипамезол",
    "атакса": "имидаклоприд",
    "бицилин": "бензатина бензилпенициллин",
    "везотил": "тилетамин",
    "ветфлоксацин": "левофлоксацин",
    "гапентин": "габапентин",
    "гельминтал": "празиквантел",
    "гепаветариум": "адеметионин",
    "дексодия": "дексмедетомидин",
    "дехинел": "празиквантел",
    "диронет": "празиквантел",
    "догферон": "интерферон",
    "фелиферон": "интерферон",
    "докситрон": "доксициклин",
    "дронтал": "празиквантел",
    "зоокард": "пимобендан",
    "ивермек": "ивермектин",
    "мильбемакс": "празиквантел",
    "празител": "празиквантел",
    "каниквантел": "празиквантел",
    "стоп-цистит": "фитопрепарат",
    "айсидивит": "витамины",
    "гамавит": "витамины",
    "кантарен": "гомеопатия",
    "хондартрон": "гомеопатия",
    # Второй проход по прайсу.
    "клавуксицин": "амоксициллин",
    "кладакса": "амоксициллин",
    "мономокс": "амоксициллин",
    "марбобел": "марбофлоксацин",
    "лефлобакт": "левофлоксацин",
    "левоксидин": "левофлоксацин",
    "кеппра": "леветирацетам",
    "карбамазепин": "карбамазепин",
    "левомицетин": "хлорамфеникол",
    "мелоксивет": "мелоксикам",
    "метрид": "метронидазол",
    "милпразон": "празиквантел",
    "пинпрамиль": "празиквантел",
    "миртацен": "миртазапин",
    "нольпаза": "пантопразол",
    "преднифарм": "преднизолон",
    "рикарфа": "карпрофен",
    "роксиор": "робенакоксиб",
    "ронколейкин": "интерлейкин-2",
    "омнипак": "йогексол",
    "маннит": "маннитол",
    "кофеин": "кофеин",
    "кальция хлорид": "кальция хлорид",
    "кальция борглюконат": "кальция борглюконат",
    "натрий хлорид": "натрия хлорид",
    "реосорбилакт": "сорбитол",
    "инспектор": "фипронил",
    "инсектал": "фипронил",
    "амит форте": "дельтаметрин",
    "лиарсин": "гомеопатия",
    "овариовит": "гомеопатия",
    "мильгама": "витамины",
    "витокей": "витамины",
    "активитон": "витамины",
    "комплекс витаминов": "витамины",
}

# Названия, по которым видно: это вакцина. Вещества у них нет, ставим только группу.
VACCINES = (
    "нобивак",
    "вакдерм",
    "гискан",
    "глобфел",
    "вакцина",
    "рабизин",
    "пуревакс",
    "мультикан",
    "эурикан",
    "феловакс",
    "биофел",
    "биокан",
)
VACCINE_GROUP = "Вакцины"

# Не препараты: расходники, инвентарь, уход, документы — вещество им не нужно.
NOT_DRUGS = (
    "воротник",
    "переноска",
    "катетер",
    "зонд",
    "пелен",
    "пелён",
    "подгузник",
    "памперс",
    "бинт",
    "салфетк",
    "лейкопластыр",
    "шприц",
    "набор",
    "капельниц",
    "паспорт",
    "карта",
    "экспресс-тест",
    "мазок",
    "контраст",
    "бальзам",
    "шампунь",
    "лосьон",
    "воск",
    "пакет для",
    "корм",
)


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
        # Ключ поиска → название вещества. Чего нет в справочнике, заведём при записи.
        by_key: dict[str, str] = {}
        for substance in Substance.objects.all():
            for key in _keys(substance):
                by_key.setdefault(key, substance.name)
        for brand, name in BRANDS.items():
            by_key.setdefault(_simple(brand), name)
        known = {s.name.lower() for s in Substance.objects.all()}

        # Длинные названия ищем первыми: «аскорбиновая кислота» важнее «кислота».
        keys = sorted(by_key, key=len, reverse=True)
        matched: list[tuple[Item, str]] = []
        vaccines: list[Item] = []
        not_drugs: list[Item] = []
        unknown: list[Item] = []
        for item in Item.objects.filter(kind=Kind.GOODS, is_active=True).prefetch_related(
            "substances"
        ):
            if item.substances.exists():
                continue
            name = f" {_simple(item.name)} "
            if any(word in name for word in VACCINES):
                vaccines.append(item)
                continue
            if any(word in name for word in NOT_DRUGS):
                not_drugs.append(item)
                continue
            found = next((by_key[key] for key in keys if f" {key} " in name or key in name), None)
            (matched.append((item, found)) if found else unknown.append(item))

        for item, name in matched[: options["show"]]:
            mark = "" if name.lower() in known else "  (вещество будет заведено)"
            self.stdout.write(f"{item.name} → {name}{mark}")
        self.stdout.write(
            self.style.SUCCESS(
                f"\nраспозналось: {len(matched)}, вакцин: {len(vaccines)}, "
                f"не препаратов: {len(not_drugs)}, не распозналось: {len(unknown)}"
            )
        )
        for item in unknown[: options["show"]]:
            self.stdout.write(self.style.WARNING(f"  ? {item.name}"))

        if not options["apply"]:
            self.stdout.write("\nЭто предварительный просмотр. Записать: --apply")
            return
        substances: dict[str, Substance] = {}
        for item, name in matched:
            substance = substances.get(name.lower())
            if substance is None:
                substance = Substance.objects.filter(name__iexact=name).first()
                if substance is None:
                    substance = Substance.objects.create(name=name.capitalize())
                    self.stdout.write(self.style.WARNING(f"новое вещество: {substance.name}"))
                substances[name.lower()] = substance
            services.set_drug_info(item, [substance], None)  # группа — по веществу
        if vaccines:
            group, _ = DrugGroup.objects.get_or_create(name=VACCINE_GROUP)
            for item in vaccines:
                services.set_drug_info(item, None, [group])
        self.stdout.write(self.style.SUCCESS(f"записано: {len(matched)}, вакцин: {len(vaccines)}"))
