"""Файлы: прикрепление к записям, проверки, скачивание с правами."""

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from core import attachments
from core.models import Attachment, Clinic, FileCategory

URL = "/api/core/attachments/"


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    attachments.register_owner("core.clinic")  # в тестах ядра файлы крепим к клинике
    yield


@pytest.fixture
def clinic(db):
    return Clinic.objects.order_by("created_at").first()


@pytest.fixture
def api(db):
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    return client


def upload(name="скан договора.pdf", content=b"%PDF-1.4 test", content_type="application/pdf"):
    return SimpleUploadedFile(name, content, content_type=content_type)


def test_attach_keeps_real_name_and_random_storage_name(clinic) -> None:
    category = FileCategory.objects.get(name="Договор")

    item = attachments.attach("core.clinic", clinic.pk, upload(), category=category)

    assert item.name == "скан договора.pdf"
    assert item.size == len(b"%PDF-1.4 test")
    assert str(item.pk) in item.file.name
    assert "скан" not in item.file.name


def test_unregistered_owner_and_missing_record_are_rejected(clinic) -> None:
    with pytest.raises(attachments.AttachmentError, match="нельзя прикреплять"):
        attachments.attach("core.user", clinic.pk, upload())
    with pytest.raises(attachments.AttachmentError, match="не найдена"):
        attachments.attach("core.clinic", "00000000-0000-0000-0000-000000000000", upload())


def test_size_limit(clinic, settings) -> None:
    settings.ATTACHMENT_MAX_MB = 0

    with pytest.raises(attachments.AttachmentError, match="больше 0 МБ"):
        attachments.attach("core.clinic", clinic.pk, upload())


def test_api_upload_list_download_and_soft_delete(api, clinic) -> None:
    created = api.post(
        URL,
        {"file": upload(), "owner_type": "core.clinic", "owner_id": str(clinic.pk)},
        format="multipart",
    )
    item_id = created.json()["id"]
    listed = api.get(f"{URL}?owner_type=core.clinic&owner_id={clinic.pk}").json()
    file = api.get(f"{URL}{item_id}/download/?download=1")
    deleted = api.delete(f"{URL}{item_id}/")

    assert created.status_code == 201
    assert [i["name"] for i in listed] == ["скан договора.pdf"]
    assert b"".join(file.streaming_content) == b"%PDF-1.4 test"
    assert "attachment" in file["Content-Disposition"]
    assert deleted.status_code == 204
    assert Attachment.all_objects.get(pk=item_id).is_deleted


def test_api_requires_owner_and_file(api, clinic) -> None:
    assert api.get(URL).status_code == 400
    no_file = api.post(URL, {"owner_type": "core.clinic", "owner_id": str(clinic.pk)})
    assert no_file.json()["file"] == ["Выберите файл."]


def test_download_requires_permission(db, clinic) -> None:
    item = attachments.attach("core.clinic", clinic.pk, upload())
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_user(username="u", password="x"))

    assert client.get(f"{URL}{item.pk}/download/").status_code == 403
