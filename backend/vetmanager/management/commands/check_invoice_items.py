"""Проверить, что все позиции из счетов VetManager есть у нас — до переноса счетов.

Берёт строки счетов, собирает разные позиции и смотрит, на что указывает связь
переноса: позиция жива, удалена или связи нет вовсе.

    python manage.py check_invoice_items
"""

from collections import Counter
from typing import Any

from django.core.management.base import BaseCommand

from catalog.models import Item
from vetmanager import client
from vetmanager.models import Imported


class Command(BaseCommand):
    help = "Проверить позиции из счетов VetManager перед переносом."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--show", type=int, default=30, help="сколько строк показать")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            rows = client.fetch("invoiceDocument")
        except client.VetManagerError as error:
            self.stdout.write(self.style.ERROR(str(error)))
            return
        used = Counter(str(row.get("good_id") or "") for row in rows)
        used.pop("", None)
        links = {
            link.external_id: str(link.target_id) for link in Imported.objects.filter(kind="item")
        }
        alive = {str(pk) for pk in Item.objects.values_list("pk", flat=True)}
        removed = {str(pk) for pk in Item.all_objects.values_list("pk", flat=True)} - alive

        ok, gone, missing = [], [], []
        for external_id, count in used.items():
            target = links.get(external_id)
            if target is None:
                missing.append((external_id, count))
            elif target in alive:
                ok.append((external_id, count))
            elif target in removed:
                gone.append((external_id, count))
            else:
                missing.append((external_id, count))

        self.stdout.write(f"строк в счетах: {len(rows)}, разных позиций: {len(used)}")
        self.stdout.write(self.style.SUCCESS(f"  найдены у нас: {len(ok)}"))
        if gone:
            self.stdout.write(
                self.style.WARNING(f"  позиция удалена у нас: {len(gone)} — строки потеряются")
            )
            for external_id, count in sorted(gone, key=lambda pair: -pair[1])[: options["show"]]:
                name = Item.all_objects.filter(pk=links[external_id]).values_list("name", flat=True)
                self.stdout.write(f"    {external_id} ({count} строк): {name.first() or '—'}")
        if missing:
            self.stdout.write(
                self.style.WARNING(
                    f"  не переносились: {len(missing)} — запустите шаг «Товары и услуги»"
                )
            )
            for external_id, count in sorted(missing, key=lambda pair: -pair[1])[: options["show"]]:
                self.stdout.write(f"    {external_id} ({count} строк)")
        if not gone and not missing:
            self.stdout.write(self.style.SUCCESS("Всё на месте — счета можно переносить."))
