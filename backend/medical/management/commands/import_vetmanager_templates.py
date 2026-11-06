"""Импорт текстовых шаблонов медкарты из VetManager.

Из файла (ответ API, сохранённый curl):
    python manage.py import_vetmanager_templates vm-templates.json

Прямо из VetManager (адрес и ключ — из окружения VETMANAGER_URL и VETMANAGER_API_KEY):
    python manage.py import_vetmanager_templates --from-api

--section treatment|recommendations|both (по умолчанию both) — на какой вкладке предлагать;
--update — заменить текст шаблонов с тем же названием (иначе они пропускаются).
"""

import os
import urllib.request
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from medical import services


class Command(BaseCommand):
    help = "Импорт текстовых шаблонов медкарты из VetManager (файл или API)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("file", nargs="?", help="JSON-ответ MedcardsTextTemplates")
        parser.add_argument("--from-api", action="store_true", help="Загрузить из VetManager")
        parser.add_argument("--section", default="both")
        parser.add_argument("--update", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["from_api"]:
            url = os.environ.get("VETMANAGER_URL", "").rstrip("/")
            key = os.environ.get("VETMANAGER_API_KEY", "")
            if not url or not key:
                raise CommandError("Задайте VETMANAGER_URL и VETMANAGER_API_KEY в окружении.")
            request = urllib.request.Request(
                f"{url}/rest/api/MedicalCards/MedcardsTextTemplates?tpls_for=1",
                headers={"X-REST-API-KEY": key, "Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 — адрес из настроек
                raw = response.read()
        elif options["file"]:
            with open(options["file"], "rb") as file:
                raw = file.read()
        else:
            raise CommandError("Укажите файл или --from-api.")
        try:
            rows = services.vetmanager_templates(raw)
            result = services.import_vetmanager_templates(
                rows, options["section"], options["update"]
            )
        except services.MedicalError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            self.style.SUCCESS(
                f"Шаблонов в файле: {len(rows)}. Добавлено: {result['created']}, "
                f"обновлено: {result['updated']}, пропущено: {result['skipped']}."
            )
        )
