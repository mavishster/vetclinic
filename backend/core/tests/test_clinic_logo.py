"""Логотип клиники: загрузка (перекодируется в PNG), показ без входа, печать, удаление."""

import io

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from core import services

User = get_user_model()


@pytest.fixture(autouse=True)
def _media(settings, tmp_path):  # type: ignore[no-untyped-def]
    settings.MEDIA_ROOT = tmp_path


def _picture(fmt: str = "JPEG", size: tuple[int, int] = (1200, 400)) -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", size, "teal").save(buffer, fmt)
    return SimpleUploadedFile(f"logo.{fmt.lower()}", buffer.getvalue())


def test_upload_reencodes_to_small_png_and_print_context_has_it(db) -> None:
    services.set_clinic_logo(_picture())

    data = services.clinic_logo_bytes()
    assert data is not None
    image = Image.open(io.BytesIO(data))
    assert image.format == "PNG" and max(image.size) == services.LOGO_MAX_PX
    assert services.common_print_context()["clinic"]["logo"].startswith("data:image/png;base64,")


def test_not_an_image_is_rejected(db) -> None:
    with pytest.raises(services.LogoError, match="прочитать"):
        services.set_clinic_logo(SimpleUploadedFile("logo.png", b"<svg onload=alert(1)>"))


def test_api_upload_needs_right_and_logo_is_public(db) -> None:
    admin = APIClient()
    admin.force_authenticate(User.objects.create_superuser(username="boss", password="x"))
    plain = APIClient()
    plain.force_authenticate(User.objects.create_user(username="plain"))
    anonymous = APIClient()

    assert anonymous.get("/api/core/clinic/logo/").status_code == 404
    denied = plain.post("/api/core/clinic/logo/", {"file": _picture("PNG")}, format="multipart")
    uploaded = admin.post("/api/core/clinic/logo/", {"file": _picture("PNG")}, format="multipart")
    shown = anonymous.get("/api/core/clinic/logo/")
    removed = admin.delete("/api/core/clinic/logo/")

    assert denied.status_code == 403
    assert uploaded.status_code == 200 and uploaded.json()["logo_version"]
    assert shown.status_code == 200 and shown["Content-Type"] == "image/png"
    assert removed.json()["logo_version"] is None
    assert anonymous.get("/api/core/clinic/logo/").status_code == 404
    assert services.common_print_context()["clinic"]["logo"] == ""
