"""Разложить позиции прайса по группам: товары и услуги со своими разделами.

Группа отвечает на вопрос «с какой полки», а не «что это за лекарство»: вид
профилактики, действующее вещество и группа препарата живут в своих полях.
Позиции раскладываются по названию, пустые группы убираются.

    python manage.py tidy_groups            # только показать
    python manage.py tidy_groups --apply    # применить
"""

import re
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import Item, ItemGroup, Kind

# Группы товаров и слова, по которым позиция в них попадает. Порядок важен:
# побеждает первое совпадение, поэтому «шприц» разбирается раньше «набора».
GOODS_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    (
        "Лабораторные",
        ("экспресс-тест", "эксперс", "экспресс тест", "тест на", "пробирк", "предметн"),
    ),
    (
        "Медматериалы",
        (
            "шприц",
            "катетер",
            "зонд",
            "система для",
            "набор для",
            "бинт",
            "салфетк",
            "лейкопластыр",
            "перчатк",
            "шовн",
            "кран",
            "игла",
            "скальпел",
            "капельниц",
            "пакет для",
            "переливан",
        ),
    ),
    (
        "Зоотовары",
        (
            "шампунь",
            "бальзам",
            "лосьон",
            "воск",
            "спрей отпугивающ",
            "кондиционер",
            "воротник",
            "переноск",
            "подгузник",
            "памперс",
            "пелен",
            "пелён",
            "игрушк",
            "поводок",
            "ошейник",
            "миск",
            "лежак",
            "когтерез",
        ),
    ),
    ("Корма", ("корм", "паштет", "лакомств", "диета")),
]
GOODS_DEFAULT = "Препараты"

# Услуги: группы и слова названия.
SERVICE_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    (
        "Лабораторные исследования",
        (
            "pcr",
            "real-time",
            "real time",
            "kit",
            "akso",
            "пцр",
            "анализ",
            "посев",
            "цитолог",
            "гистолог",
            "биохим",
            "оак",
            "оам",
            "гематолог",
            "титр",
            "смыв",
            "соскоб",
            "микроскоп",
            "бак.",
            "бакпосев",
            "кровь",
            "моча",
            "кал ",
            "копролог",
            "иммунофермент",
            "ифа",
            "коагулограмм",
            "электролит",
            "гормон",
        ),
    ),
    (
        "Визуальная диагностика",
        ("узи", "рентген", "кт ", "мрт", "эндоскоп", "экг", "эхо", "офтальмоскоп", "отоскоп"),
    ),
    (
        "Вакцинация и профилактика",
        ("вакцин", "прививк", "ревакцин", "дегельминт", "глистоген"),
    ),
    ("Эвтаназия и кремация", ("эвтаназ", "усыплен", "кремац", "захоронен", "утилизац")),
    ("Приём и консультации", ("приём", "прием", "консультац", "вызов", "осмотр")),
    ("Диагностика", ("взятие", "исследован", "мазок", "проба")),
    (
        "Стоматология",
        ("стоматолог", "зуб", "пародонт", "зубн", "ультразвуковая чистка", "полировк"),
    ),
    (
        "Акушерство и гинекология",
        ("принятие род", "родоразреш", "кесарев", "акушер", "гинеколог", "беремен", "вагинальн"),
    ),
    ("Хирургия и анестезия", ("операц", "хирург", "наркоз", "анестез", "кастрац", "стерилизац")),
    ("Стационар", ("стационар", "койко", "наблюден", "передержк", "гостиниц")),
    ("Груминг", ("груминг", "стрижк", "когт", "купан", "мытьё", "мытье")),
    (
        "Процедуры",
        ("инъекц", "укол", "капельниц", "обработк", "чистк", "перевязк", "промыван", "клизм"),
    ),
    ("Прочее", ("паспорт", "справк", "оформлен", "документ", "чип")),
]
# Нераспознанную услугу не трогаем: лучше оставить как есть, чем свалить в «Прочее».
SERVICE_DEFAULT = ""


def _simple(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("ё", "е")).strip()


def _group_for(name: str, rules: list[tuple[str, tuple[str, ...]]], default: str) -> str:
    simple = _simple(name)
    for group, words in rules:
        if any(_simple(word) in simple for word in words):
            return group
    return default


class Command(BaseCommand):
    help = "Разложить позиции по группам товаров и услуг, убрать пустые группы."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--apply", action="store_true", help="применить (иначе показать)")
        parser.add_argument("--show", type=int, default=50, help="сколько строк показать")
        parser.add_argument(
            "--other",
            action="store_true",
            help="показать услуги из «Прочее», которые не удалось разложить по названию",
        )

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        moves: list[tuple[Item, str, str]] = []
        leftovers: list[Item] = []
        for item in Item.objects.exclude(kind=Kind.COMBO).select_related("group"):
            rules, default = (
                (GOODS_GROUPS, GOODS_DEFAULT)
                if item.kind == Kind.GOODS
                else (SERVICE_GROUPS, SERVICE_DEFAULT)
            )
            wanted = _group_for(item.name, rules, default)
            if not wanted:
                if item.group and _simple(item.group.name).startswith("проч"):
                    leftovers.append(item)
                continue  # не поняли, что это за услуга — оставляем её группу
            if item.group and _simple(item.group.name) == _simple(wanted):
                continue
            moves.append((item, item.group.name if item.group else "—", wanted))

        for item, was, becomes in moves[: options["show"]]:
            self.stdout.write(f"{item.name}\n    {was} → {becomes}")
        self.stdout.write(self.style.SUCCESS(f"\nпереложить: {len(moves)}"))
        self.stdout.write(f"услуг в «Прочее», которые не удалось разложить: {len(leftovers)}")
        if options["other"]:
            for item in sorted(leftovers, key=lambda i: i.name):
                self.stdout.write(f"    {item.name}")

        if not options["apply"]:
            self.stdout.write("Это предварительный просмотр. Применить: --apply")
            return

        groups: dict[tuple[str, str], ItemGroup] = {}
        for item, _was, becomes in moves:
            key = (becomes.lower(), item.kind)
            group = groups.get(key)
            if group is None:
                group = ItemGroup.objects.filter(name__iexact=becomes, kind=item.kind).first()
                if group is None:
                    group = ItemGroup.objects.create(name=becomes, kind=item.kind)
                groups[key] = group
            item.group = group
            item.save(update_fields=["group"])

        empty = [
            group
            for group in ItemGroup.objects.all()
            if not Item.all_objects.filter(group=group).exists()
        ]
        for group in empty:
            self.stdout.write(f"убрана пустая группа: {group.name}")
            group.delete()
        self.stdout.write(
            self.style.SUCCESS(f"переложено: {len(moves)}, убрано пустых групп: {len(empty)}")
        )
