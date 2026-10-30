import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

URL = "/api/core/counterparties/"


@pytest.fixture
def api(db):
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    return client


def test_counterparty_with_requisites(api) -> None:
    response = api.post(
        URL,
        {"name": 'ООО "Торговый дом-ВИК"', "contact": "ВИК", "city": "Москва", "phone": "+74957776767",
         "inn": "5027233428", "bik": "044525700", "settlement_account": "40702810000000000001"},
        format="json",
    )  # fmt: skip

    assert response.status_code == 201
    assert response.json()["person_type"] == "legal"
    assert response.json()["for_receipts"] is True


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("inn", "12345", "ИНН"),
        ("bik", "04452570X", "БИК"),
        ("settlement_account", "123", "Расчётный счёт"),
    ],
)
def test_requisites_are_checked(api, field, value, message) -> None:
    response = api.post(URL, {"name": "Поставщик", field: value}, format="json")

    assert response.status_code == 400
    assert message in response.json()[field][0]


def test_filter_by_where_to_show(api) -> None:
    api.post(URL, {"name": "Ветпром"}, format="json")
    api.post(
        URL, {"name": "Арендодатель", "for_receipts": False, "for_write_offs": False}, format="json"
    )

    receipts = [c["name"] for c in api.get(f"{URL}?use=receipt").json()]
    cash = [c["name"] for c in api.get(f"{URL}?use=cash").json()]

    assert receipts == ["Ветпром"]
    assert cash == ["Арендодатель", "Ветпром"]
