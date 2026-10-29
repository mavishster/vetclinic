import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from clients.models import City, Client, Street

URL = "/api/clients/clients/"


@pytest.fixture
def api(db):
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    return client


def create(api, **data):
    return api.post(URL, {"last_name": "Иванова", **data}, format="json")


def test_create_client_with_phones_and_address(api) -> None:
    city = City.objects.create(name="Казань")
    street = Street.objects.create(name="Баумана", city=city)

    response = create(
        api,
        first_name="Анна",
        city=str(city.pk),
        street=str(street.pk),
        phones=[{"number": "+7 912 345-67-89"}, {"number": "222-33-44", "kind": "home"}],
    )

    assert response.status_code == 201
    data = response.json()
    assert data["full_name"] == "Иванова Анна"
    assert data["city_name"] == "Казань"
    assert data["phones"][0] == {
        "kind": "mobile",
        "number": "+7 912 345-67-89",
        "is_primary": True,
        "comment": "",
    }


def test_validation_errors_are_readable(api) -> None:
    no_name = create(api, last_name=" ")
    bad_phone = create(api, phones=[{"number": "1"}])
    bad_discount = create(api, discount_percent="150")

    assert no_name.status_code == 400
    assert "Проверьте номер" in bad_phone.json()["non_field_errors"][0]
    assert bad_discount.status_code == 400


def test_update_keeps_phones_when_not_sent(api) -> None:
    client_id = create(api, phones=[{"number": "+7 912 345-67-89"}]).json()["id"]

    api.patch(f"{URL}{client_id}/", {"first_name": "Анна"}, format="json")

    assert Client.objects.get(pk=client_id).phones.count() == 1


def test_list_search_filters_and_pagination(api) -> None:
    create(api, first_name="Анна", phones=[{"number": "+7 912 345-67-89"}])
    create(api, last_name="Петров", status="inactive")
    create(api, last_name="Сидоров", in_blacklist=True)

    def names(query):
        return [c["last_name"] for c in api.get(f"{URL}?{query}").json()["results"]]

    assert names("search=4567") == ["Иванова"]
    assert names("status=active,temporary") == ["Иванова", "Сидоров"]
    assert names("blacklist=true") == ["Сидоров"]
    assert api.get(f"{URL}?page_size=2").json()["count"] == 3


def test_duplicates_endpoint(api) -> None:
    anna_id = create(api, first_name="Анна", phones=[{"number": "+7 912 345-67-89"}]).json()["id"]

    found = api.get(f"{URL}duplicates/?last_name=Смирнова&phone=8 912 345 67 89").json()
    itself = api.get(f"{URL}duplicates/?last_name=Иванова&first_name=Анна&exclude={anna_id}")

    assert found[0]["id"] == anna_id
    assert itself.json() == []


def test_delete_is_soft(api) -> None:
    client_id = create(api).json()["id"]

    assert api.delete(f"{URL}{client_id}/").status_code == 204
    assert Client.all_objects.get(pk=client_id).is_deleted


def test_requires_permissions(db) -> None:
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_user(username="u", password="x"))

    assert client.get(URL).status_code == 403


def test_streets_filter_by_city(api) -> None:
    kazan, moscow = City.objects.create(name="Казань"), City.objects.create(name="Москва")
    Street.objects.create(name="Баумана", city=kazan)
    Street.objects.create(name="Тверская", city=moscow)

    streets = api.get(f"/api/clients/streets/?city={kazan.pk}").json()

    assert [s["name"] for s in streets] == ["Баумана"]
