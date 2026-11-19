"""Перенести позиции прайса, которых у нас нет, и показать причину по каждой.

Шаг «Товары и услуги» пропускает уже перенесённые и молча складывает отказы
в общий список. Команда переносит только недостающие и пишет, почему именно
позиция не прошла: без неё непонятно, чего не хватает для переноса счетов.

    python manage.py import_missing_items            # только показать
    python manage.py import_missing_items --apply    # перенести
"""

from collections import Counter
from typing import Any

from django.core.management.base import BaseCommand

from catalog.models import Item
from vetmanager import client, services
from vetmanager.models import Imported


class Command(BaseCommand):
    help = "Перенести недостающие позиции прайса и показать причины отказов."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--apply", action="store_true", help="перенести (иначе показать)")
        parser.add_argument("--show", type=int, default=40, help="сколько строк показать")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            rows = client.fetch("Good")
        except client.VetManagerError as error:
            self.stdout.write(self.style.ERROR(str(error)))
            return
        alive = {str(pk) for pk in Item.objects.values_list("pk", flat=True)}
        linked = {
            link.external_id
            for link in Imported.objects.filter(kind="item")
            if str(link.target_id) in alive
        }
        missing = [row for row in rows if str(row.get("id")) not in linked]
        self.stdout.write(f"в VetManager: {len(rows)}, нет у нас: {len(missing)}")
        if not missing:
            self.stdout.write(self.style.SUCCESS("Все позиции на месте."))
            return

        kinds = Counter(
            "услуга" if (row.get("group") or {}).get("is_service") else "товар" for row in missing
        )
        self.stdout.write(
            f"из них: {', '.join(f'{count} {kind}' for kind, count in kinds.items())}"
        )

        if not options["apply"]:
            for row in missing[: options["show"]]:
                group = (row.get("group") or {}).get("title", "—")
                self.stdout.write(f"  {row.get('id')}: {row.get('title')} · группа «{group}»")
            self.stdout.write("\nЭто предварительный просмотр. Перенести: --apply")
            return

        # Связи на удалённые у нас позиции мешают переносу: шаг считает их перенесёнными.
        stale = [
            link
            for link in Imported.objects.filter(kind="item")
            if str(link.target_id) not in alive
        ]
        for link in stale:
            link.delete()

        result = services.import_items(missing)
        self.stdout.write(
            self.style.SUCCESS(f"перенесено: {result.created}, пропущено: {result.skipped}")
        )
        if result.errors:
            self.stdout.write(self.style.WARNING(f"не прошли: {len(result.errors)}"))
            for line in result.errors[: options["show"]]:
                self.stdout.write(f"  {line}")
