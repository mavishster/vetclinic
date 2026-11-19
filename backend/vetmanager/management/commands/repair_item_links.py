"""Починить связи с VetManager, оставшиеся на объединённых позициях.

Пока объединение не переводило связь на оставшуюся позицию, ссылки указывали
на удалённую. Команда ищет для каждой такой связи живую позицию по названию
из VetManager и переставляет связь на неё.

    python manage.py repair_item_links            # только показать
    python manage.py repair_item_links --apply    # починить
"""

from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import Item
from vetmanager import client, tidy
from vetmanager.models import Imported


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
        ours: dict[str, Item] = {}
        for item in Item.objects.all():
            ours.setdefault(_key(item.name), item)

        fixed, unknown = [], []
        for link in broken:
            name = names.get(link.external_id, "")
            found = ours.get(_key(name)) if name else None
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
