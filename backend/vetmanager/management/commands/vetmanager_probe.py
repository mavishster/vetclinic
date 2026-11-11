"""Что отдаёт API VetManager: сколько записей и какие поля — чтобы сверить перенос.

python manage.py vetmanager_probe Good GoodSaleParam Client Pet
"""

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from vetmanager import client

DEFAULT = [
    "Unit",
    "GoodGroup",
    "Good",
    "GoodSaleParam",
    "Client",
    "Pet",
    "PetType",
    "Breed",
    "Admission",
    "Invoice",
]


class Command(BaseCommand):
    help = "Показать, что отдаёт API VetManager (поля и пример записи)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("models", nargs="*", help=f"по умолчанию: {', '.join(DEFAULT)}")
        parser.add_argument("--rows", type=int, default=1, help="сколько примеров показать")

    def handle(self, *args: Any, **options: Any) -> None:
        for model in options["models"] or DEFAULT:
            try:
                found = client.sample(model, options["rows"])
            except client.VetManagerError as error:
                self.stdout.write(self.style.WARNING(f"{model}: {error}"))
                continue
            self.stdout.write(self.style.SUCCESS(f"\n{model}: записей {found['total']}"))
            self.stdout.write("  поля: " + ", ".join(found["fields"]))
            for row in found["rows"]:
                self.stdout.write("  пример: " + json.dumps(row, ensure_ascii=False)[:1500])
        if not client.is_configured():
            raise CommandError("Задайте VETMANAGER_URL и VETMANAGER_API_KEY в .env.")
