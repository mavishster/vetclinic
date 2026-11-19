"""Починить связи с VetManager, оставшиеся на объединённых позициях.

Пока объединение не переводило связь на оставшуюся позицию, ссылки указывали
на удалённую. Команда ищет для каждой такой связи живую позицию по названию
из VetManager и переставляет связь на неё.

    python manage.py repair_item_links            # только показать
    python manage.py repair_item_links --apply    # починить
"""

import re
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import Item
from vetmanager import client, tidy
from vetmanager.models import Imported

# Слова фасовки и формы выпуска: в названиях они пишутся как придётся, и из-за
# них «Физраствор 100мл» не совпадал с нашим «Физраствор фл. 100мл».
_NOISE = re.compile(
    r"\b(фл|флак\w*|уп|упак\w*|таб|табл\w*|капс\w*|амп\w*|мл|мг|мкг|г|кг|л|доз\w*|"
    r"шт|саше|пипетк\w*|тюбик\w*|туба|пакет\w*|кан|р-р|раствор|инъекц\w*|pet)\b",
    re.IGNORECASE,
)


# Дозировка: её выбрасывать нельзя — «Вазосан 2,5мг» и «Вазосан 5мг» разные препараты.
_DOSE = re.compile(r"(\d+[.,]?\d*)\s*(мг|мкг|ме|ед|%)", re.IGNORECASE)


def _doses(name: str) -> str:
    """Дозировки из названия: «Вазосан 2,5мг уп. 30 табл.» → «2.5мг»."""
    found = {f"{amount.replace(',', '.')}{unit.lower()}" for amount, unit in _DOSE.findall(name)}
    return " ".join(sorted(found))


def _loose_key(name: str) -> str:
    """Название без чисел, процентов и слов фасовки: «Физраствор фл. 100мл» → «физраствор».

    Второй заход поиска: в VetManager и у нас одна позиция подписана по-разному,
    и строгое сравнение их не связывает.
    """
    text = _NOISE.sub(" ", _key(name))
    text = re.sub(r"[\d.,%*№()/+-]+", " ", text)
    return " ".join([*text.split(), _doses(name)]).strip()


def _key(name: str) -> str:
    """Название без фасовки, в нижнем регистре: «Ациломаг 100 мл (МАГ)» → «ациломаг»."""
    return " ".join(tidy._clean(name).lower().replace("ё", "е").split())


class Command(BaseCommand):
    help = "Перевести связи с VetManager с удалённых позиций на оставшиеся."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--apply", action="store_true", help="починить (иначе показать)")
        parser.add_argument("--show", type=int, default=40, help="сколько строк показать")

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        alive = {str(pk) for pk in Item.objects.values_list("pk", flat=True)}
        broken = [
            link
            for link in Imported.objects.filter(kind="item")
            if str(link.target_id) not in alive
        ]
        if not broken:
            self.stdout.write(self.style.SUCCESS("Битых связей нет."))
            return
        try:
            names = {
                str(row.get("id")): str(row.get("title") or "") for row in client.fetch("Good")
            }
        except client.VetManagerError as error:
            self.stdout.write(self.style.ERROR(str(error)))
            return

        # Живые позиции по очищенному названию: «Ациломаг 100 мл (МАГ)» → «ациломаг».
        # Для обоих заходов храним все подходящие: если их несколько, выбирать
        # наугад нельзя — «Веткокцин 5% 10 мл» и «100 мл» дают одно и то же название.
        ours: dict[str, list[Item]] = {}
        loose: dict[str, list[Item]] = {}
        for item in Item.objects.all():
            ours.setdefault(_key(item.name), []).append(item)
            loose.setdefault(_loose_key(item.name), []).append(item)

        fixed, unknown = [], []
        for link in broken:
            name = names.get(link.external_id, "")
            found = None
            for table in (ours, loose) if name else ():
                key = _key(name) if table is ours else _loose_key(name)
                candidates = table.get(key, [])
                if len(candidates) == 1:
                    found = candidates[0]
                    break
            (fixed.append((link, name, found)) if found else unknown.append((link, name)))

        for link, name, found in fixed[: options["show"]]:
            self.stdout.write(f"{name or link.external_id} → {found.name}")
        self.stdout.write(
            self.style.SUCCESS(f"\nпочиним: {len(fixed)}, не нашли пару: {len(unknown)}")
        )
        for link, name in unknown[: options["show"]]:
            self.stdout.write(self.style.WARNING(f"  ? {name or link.external_id}"))

        if not options["apply"]:
            self.stdout.write("\nЭто предварительный просмотр. Починить: --apply")
            return
        for link, _name, found in fixed:
            link.target_id = found.pk
            link.save(update_fields=["target_id"])
        self.stdout.write(self.style.SUCCESS(f"починено: {len(fixed)}"))
