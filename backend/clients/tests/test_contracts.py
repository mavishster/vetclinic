from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from clients import services
from clients.models import Client, ClientContract
from clients.services import ClientError
from core import attachments


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def client_(db):
    return services.save_client(Client(last_name="Иванова"))


@pytest.fixture
def api(db):
    api = APIClient()
    api.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    return api


def scan(owner):
    return attachments.attach("clients.client", owner.pk, SimpleUploadedFile("д.pdf", b"x"))


def test_number_is_issued_when_empty(client_) -> None:
    contract = services.save_contract(
        ClientContract(client=client_, number="", date=date(2026, 1, 5))
    )

    assert contract.number.endswith("-000001")


def test_manual_number_and_validity_period(client_) -> None:
    with pytest.raises(ClientError, match="раньше его даты"):
        services.save_contract(
            ClientContract(
                client=client_, number="15/26", date=date(2026, 2, 1), valid_until=date(2026, 1, 1)
            )
        )


def test_scan_must_belong_to_same_client(client_) -> None:
    other = services.save_client(Client(last_name="Петров"))

    with pytest.raises(ClientError, match="этому же клиенту"):
        services.save_contract(
            ClientContract(
                client=client_, number="1", date=date(2026, 1, 1), attachment=scan(other)
            )
        )


def test_contract_flag_counts_only_valid_contracts(client_) -> None:
    expired = services.save_client(Client(last_name="Петров"))
    today = timezone.localdate()
    services.save_contract(ClientContract(client=client_, number="1", date=today))
    services.save_contract(
        ClientContract(
            client=expired,
            number="2",
            date=today - timedelta(days=400),
            valid_until=today - timedelta(days=35),
        )
    )

    flags = dict(
        services.with_contract_flag(Client.objects.all()).values_list("last_name", "has_contract")
    )

    assert flags == {"Иванова": True, "Петров": False}
    assert services.has_active_contract(client_)


def test_api_contract_with_scan_and_client_filter(api, client_) -> None:
    file = scan(client_)
    created = api.post(
        "/api/clients/contracts/",
        {"client": str(client_.pk), "date": "2026-01-10", "attachment": str(file.pk)},
        format="json",
    )
    services.save_client(Client(last_name="Петров"))

    with_contract = api.get("/api/clients/clients/?contract=yes").json()["results"]
    without = api.get("/api/clients/clients/?contract=no").json()["results"]
    card = api.get(f"/api/clients/clients/{client_.pk}/").json()

    assert created.status_code == 201
    assert created.json()["attachment_name"] == "д.pdf"
    assert created.json()["is_active"] is True
    assert [c["last_name"] for c in with_contract] == ["Иванова"]
    assert [c["last_name"] for c in without] == ["Петров"]
    assert card["has_contract"] is True


def test_client_files_api(api, client_) -> None:
    response = api.post(
        "/api/core/attachments/",
        {
            "file": SimpleUploadedFile("паспорт.jpg", b"img", content_type="image/jpeg"),
            "owner_type": "clients.client",
            "owner_id": str(client_.pk),
        },
        format="multipart",
    )

    assert response.status_code == 201
    listed = api.get(f"/api/core/attachments/?owner_type=clients.client&owner_id={client_.pk}")
    assert [f["name"] for f in listed.json()] == ["паспорт.jpg"]


def test_list_shows_contract_number_and_expired(api, client_) -> None:
    """В списке клиентов — номер действующего договора; если действующего нет — последний «истёк»."""
    other = services.save_client(Client(last_name="Петрова"))
    none = services.save_client(Client(last_name="Сидорова"))
    services.save_contract(ClientContract(client=client_, number="К-1", date=date(2026, 1, 5)))
    services.save_contract(
        ClientContract(
            client=other, number="К-2", date=date(2020, 1, 5), valid_until=date(2020, 12, 31)
        )
    )

    rows = {r["last_name"]: r for r in api.get("/api/clients/clients/").json()["results"]}

    assert rows["Иванова"]["contract_number"] == "К-1" and not rows["Иванова"]["contract_expired"]
    assert rows["Петрова"]["contract_number"] == "К-2" and rows["Петрова"]["contract_expired"]
    assert rows["Петрова"]["has_contract"] is False
    assert rows[none.last_name]["contract_number"] == ""


def test_new_client_gets_usual_type_by_default(db) -> None:
    from clients.models import ClientType

    usual = ClientType.objects.get(name="Обычный")
    breeder = ClientType.objects.get(name="Заводчик")

    assert services.save_client(Client(last_name="Новый")).client_type == usual
    # Явно выбранный тип не меняется.
    assert (
        services.save_client(Client(last_name="Заводчик", client_type=breeder)).client_type
        == breeder
    )


def test_list_shows_address(api, client_) -> None:
    from clients.models import City, Street

    city = City.objects.create(name="Бишкек")
    client_.city, client_.street = city, Street.objects.create(name="улица Ленина", city=city)
    client_.house = "72 кв. 3"
    services.save_client(client_)

    row = api.get("/api/clients/clients/").json()["results"][0]

    assert row["address"] == "улица Ленина, 72 кв. 3"
    assert row["balance"] == "0" and row["last_invoice_at"] is None
