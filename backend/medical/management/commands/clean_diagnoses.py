"""Прибрать названия в справочнике диагнозов.

Из VetManager названия приезжали с разметкой: «<br/>Спленит». Команда убирает теги,
лишние пробелы и делает первую букву заглавной. Если после уборки два диагноза
совпали, они сводятся в один — приёмы переносятся на оставшийся.

    python manage.py clean_diagnoses --dry-run   # только показать
    python manage.py clean_diagnoses             # применить
"""

import html
import re
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from medical.models import Diagnosis, VisitDiagnosis


def tidy(name: str) -> str:
    text = " ".join(html.unescape(re.sub(r"<[^>]*>", " ", name)).split()).strip(" .,;-—")
    return text[:1].upper() + text[1:] if text else ""


class Command(BaseCommand):
    help = "Убрать разметку из названий диагнозов и свести одинаковые."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true", help="только показать, не менять")

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        renamed = merged = 0
        by_name = {d.name.lower(): d for d in Diagnosis.objects.all()}
        for diagnosis in list(Diagnosis.objects.all()):
            clean = tidy(diagnosis.name)[:150]
            if not clean or clean == diagnosis.name:
                continue
            twin = by_name.get(clean.lower())
            if twin is not None and twin.pk != diagnosis.pk:
                self.stdout.write(f"свести: «{diagnosis.name}» → «{twin.name}»")
                if not options["dry_run"]:
                    VisitDiagnosis.objects.filter(diagnosis=diagnosis).update(diagnosis=twin)
                    diagnosis.delete()
                merged += 1
                continue
            self.stdout.write(f"«{diagnosis.name}» → «{clean}»")
            if not options["dry_run"]:
                diagnosis.name = clean
                diagnosis.save(update_fields=["name"])
            by_name[clean.lower()] = diagnosis
            renamed += 1
        done = "показано" if options["dry_run"] else "готово"
        self.stdout.write(self.style.SUCCESS(f"{done}: переименовано {renamed}, сведено {merged}"))
