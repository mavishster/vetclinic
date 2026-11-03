"""Подпись на планшете и фото клиента."""

import base64
import io
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from clients import services
from clients.models import Client, ClientContract, SignatureRequest, SigningStation
from core import services as core
from core.models import Attachment, PrintTemplate


def png_data_url() -> str:
    image = Image.new("RGBA", (300, 100), (255, 255, 255, 0))
    for x in range(20, 280):
        image.putpixel((x, 50), (0, 0, 0, 255))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def jpeg(size=(1600, 1200)) -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", size, (120, 140, 160)).save(buffer, "JPEG")
    return SimpleUploadedFile("photo.jpg", buffer.getvalue(), content_type="image/jpeg")


@pytest.fixture
def admin(db):
    return get_user_model().objects.create_superuser(
        username="adm", password="x", last_name="Орлова"
    )


@pytest.fixture
def station(db):
    role = Group.objects.create(name="Планшет подписи")
    core.set_special_permissions(role, {"clients.sign_on_station"})
    user = get_user_model().objects.create_user(username="tablet", password="x")
    user.groups.add(role)
    return SigningStation.objects.create(name="Стойка", user=user)


@pytest.fixture
def client_(db):
    return services.save_client(
        Client(last_name="Петров", first_name="Пётр"), [{"number": "+7 900 111-22-33"}]
    )


def template(name):
    return PrintTemplate.objects.get(kind="client_document", name__startswith=name)


def test_send_freezes_text_and_one_pending_per_station(admin, station, client_) -> None:
    first = services.send_for_signature(client_, template("Договор"), station, admin, "contract")
    second = services.send_for_signature(client_, template("Согласие"), station, admin, "consent")

    first.refresh_from_db()
    assert first.status == "cancelled" and second.status == "pending"
    assert "Петров Пётр" in second.html and "+7 900 111-22-33" in second.html
    assert len(second.content_hash) == 64
    assert services.pending_for(station) == second


def test_sign_contract_makes_pdf_in_client_files(admin, station, client_) -> None:
    contract = ClientContract.objects.create(
        client=client_, number="К-15", date=timezone.localdate()
    )
    request = services.send_for_signature(
        client_, template("Договор"), station, admin, "contract", contract
    )

    services.sign(request, station, png_data_url(), "127.0.0.1 · test")

    request.refresh_from_db()
    contract.refresh_from_db()
    assert request.status == "signed" and request.result_id
    assert contract.attachment_id == request.result_id
    pdf = Attachment.objects.get(pk=request.result_id)
    assert pdf.file.read().startswith(b"%PDF") and pdf.category.name == "Договор"
    with pytest.raises(services.SigningError, match="уже подписан"):
        services.sign(request, station, png_data_url())


def test_sign_rules(admin, station, client_) -> None:
    other_user = get_user_model().objects.create_user(username="tablet2", password="x")
    other = SigningStation.objects.create(name="Кабинет", user=other_user)
    request = services.send_for_signature(client_, template("Согласие"), station, admin, "consent")

    with pytest.raises(services.SigningError, match="другой планшет"):
        services.sign(request, other, png_data_url())
    with pytest.raises(services.SigningError, match="Подпись не получена"):
        services.sign(request, station, "data:image/png;base64,мусор")
    SignatureRequest.objects.filter(pk=request.pk).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )
    with pytest.raises(services.SigningError, match="истекло"):
        services.sign(request, station, png_data_url())


def test_consent_enables_photo_which_is_resized(admin, station, client_) -> None:
    with pytest.raises(services.ClientError, match="согласия"):
        services.save_photo(client_, jpeg())
    request = services.send_for_signature(client_, template("Согласие"), station, admin, "consent")
    services.sign(request, station, png_data_url())
    client_.refresh_from_db()

    photo = services.save_photo(client_, jpeg())

    assert client_.photo_consent_at and client_.photo == photo
    assert max(Image.open(photo.file).size) == 800


def test_station_api_and_isolation(admin, station, client_) -> None:
    staff = APIClient()
    staff.force_authenticate(admin)
    tablet = APIClient()
    tablet.force_authenticate(station.user)

    idle = tablet.get("/api/clients/signing/current/").json()
    sent = staff.post("/api/clients/signatures/", {"client": str(client_.pk), "template": str(template("Согласие").pk),
                                                   "station": str(station.pk), "purpose": "consent"}, format="json").json()  # fmt: skip
    shown = tablet.get("/api/clients/signing/current/").json()
    signed = tablet.post(
        "/api/clients/signing/sign/",
        {"id": shown["id"], "signature": png_data_url()},
        format="json",
    )
    status = staff.get(f"/api/clients/signatures/{sent['id']}/").json()
    photo = staff.post(
        f"/api/clients/clients/{client_.pk}/photo/", {"file": jpeg()}, format="multipart"
    )

    assert idle == {"station": "Стойка"}
    assert shown["title"].startswith("Согласие") and "Петров" in shown["html"]
    assert signed.status_code == 200 and status["status"] == "signed"
    assert photo.json()["photo"] and photo.json()["photo_consent_at"]
    assert (
        tablet.get(f"/api/clients/clients/{client_.pk}/").status_code == 403
    )  # планшету данные клиентов не видны
    assert staff.get("/api/clients/signing/current/").status_code == 403  # не планшет


def test_photo_on_station(admin, station, client_) -> None:
    from clients.models import PhotoRequest

    with pytest.raises(services.ClientError, match="согласия"):
        services.request_photo(client_, station, admin)
    sign = services.send_for_signature(client_, template("Согласие"), station, admin, "consent")
    services.sign(sign, station, png_data_url())
    client_.refresh_from_db()

    photo = services.request_photo(client_, station, admin)
    assert services.pending_photo_for(station) == photo
    services.take_photo_on_station(photo, station, jpeg())

    photo.refresh_from_db()
    client_.refresh_from_db()
    assert photo.status == PhotoRequest.Status.DONE and client_.photo == photo.result
    with pytest.raises(services.SigningError, match="уже сделан"):
        services.take_photo_on_station(photo, station, jpeg())


def test_photo_on_station_api(admin, station, client_) -> None:
    client_.photo_consent_at = timezone.now()
    client_.save()
    staff = APIClient()
    staff.force_authenticate(admin)
    tablet = APIClient()
    tablet.force_authenticate(station.user)

    asked = staff.post(
        "/api/clients/photo-requests/",
        {"client": str(client_.pk), "station": str(station.pk)},
        format="json",
    ).json()
    task = tablet.get("/api/clients/signing/current/").json()
    taken = tablet.post(
        "/api/clients/signing/photo/", {"id": task["id"], "file": jpeg()}, format="multipart"
    )
    status = staff.get(f"/api/clients/photo-requests/{asked['id']}/").json()

    assert task["task"] == "photo" and task["client_name"] == "Петров Пётр"
    assert taken.status_code == 200 and status["status"] == "done" and status["result"]
    assert (
        tablet.post(
            "/api/clients/photo-requests/",
            {"client": str(client_.pk), "station": str(station.pk)},
            format="json",
        ).status_code
        == 403
    )


def test_uploaded_html_is_never_shown_inline(admin, client_) -> None:
    api = APIClient()
    api.force_authenticate(admin)
    evil = SimpleUploadedFile("page.html", b"<script>alert(1)</script>", content_type="text/html")
    attachment = api.post(
        "/api/core/attachments/",
        {"owner_type": "clients.client", "owner_id": str(client_.pk), "file": evil},
        format="multipart",
    ).json()
    image = jpeg()
    picture = api.post(
        "/api/core/attachments/",
        {"owner_type": "clients.client", "owner_id": str(client_.pk), "file": image},
        format="multipart",
    ).json()

    html = api.get(f"/api/core/attachments/{attachment['id']}/download/")
    jpg = api.get(f"/api/core/attachments/{picture['id']}/download/")

    assert html["Content-Type"] == "application/octet-stream" and html[
        "Content-Disposition"
    ].startswith("attachment")
    assert (
        html["X-Content-Type-Options"] == "nosniff" and "sandbox" in html["Content-Security-Policy"]
    )
    assert jpg["Content-Type"] == "image/jpeg" and jpg["Content-Disposition"].startswith("inline")
