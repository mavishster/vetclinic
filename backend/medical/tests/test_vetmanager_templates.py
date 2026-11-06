"""Импорт текстовых шаблонов медкарты из VetManager (ответ MedcardsTextTemplates)."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from rest_framework.test import APIClient

from medical import services
from medical.models import TextTemplate

VM = {
    "data": {
        "medicalcards": [
            {"id": "1", "title": "Абсцесс", "full_text": '<p><em>Назначения:</em></p><p>новокаин 0,5% ___ + кламоксил___<o:p></o:p></p><script>alert(1)</script>'},
            {"id": "2", "title": " Чек-лист приёма ", "full_text": "<ol><li>Как давно симптомы?</li></ol>"},
            {"id": "3", "title": "Пустой", "full_text": ""},
        ]
    },
    "success": True,
}  # fmt: skip


def test_import_cleans_html_turns_blanks_into_fields_and_skips_existing(db) -> None:
    rows = services.vetmanager_templates(json.dumps(VM))

    first = services.import_vetmanager_templates(rows)
    again = services.import_vetmanager_templates(rows)
    abscess = TextTemplate.objects.get(name="Абсцесс")

    assert first == {"created": 2, "updated": 0, "skipped": 1}
    assert again == {"created": 0, "updated": 0, "skipped": 3}
    assert abscess.owner is None and abscess.section == "both"
    assert "[___] + кламоксил[___]" in abscess.body_html
    assert "<script" not in abscess.body_html and "o:p" not in abscess.body_html
    assert TextTemplate.objects.filter(name="Чек-лист приёма").exists()


def test_update_replaces_text_and_section_is_checked(db) -> None:
    rows = services.vetmanager_templates(VM)
    services.import_vetmanager_templates(rows, "recommendations")
    rows[0]["full_text"] = "<p>Новый текст</p>"

    result = services.import_vetmanager_templates(rows, update=True)

    assert result["updated"] == 2
    assert TextTemplate.objects.get(name="Абсцесс").body_html == "<p>Новый текст</p>"
    with pytest.raises(services.MedicalError, match="вкладка"):
        services.import_vetmanager_templates(rows, "anamnesis")


def test_not_a_vetmanager_answer_is_rejected(db) -> None:
    with pytest.raises(services.MedicalError, match="JSON"):
        services.vetmanager_templates("<html>")
    with pytest.raises(services.MedicalError, match="medicalcards"):
        services.vetmanager_templates({"data": {}})


def test_api_and_command(db, tmp_path) -> None:
    api = APIClient()
    api.force_authenticate(get_user_model().objects.create_superuser(username="boss", password="x"))
    upload = SimpleUploadedFile("vm.json", json.dumps(VM).encode())

    answer = api.post("/api/medical/text-templates/import-vetmanager/", {"file": upload, "section": "treatment"},
                      format="multipart")  # fmt: skip
    path = tmp_path / "vm.json"
    path.write_text(json.dumps(VM), encoding="utf-8")
    call_command("import_vetmanager_templates", str(path), "--update")

    assert answer.status_code == 200 and answer.json()["created"] == 2
    assert TextTemplate.objects.get(name="Абсцесс").section == "treatment"
