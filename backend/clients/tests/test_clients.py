"""Клиенты: телефоны, сохранение, поиск, дубли."""

import pytest

from clients import services
from clients.models import City, Client, ClientPhone, Street, phone_search_key
from clients.services import ClientError


def make_client(last_name: str, first_name: str = "", phones: list[str] | None = None, **fields):
    client = Client(last_name=last_name, first_name=first_name, **fields)
    return services.save_client(client, [{"number": p} for p in phones or []])


@pytest.mark.parametrize(
    "number", ["8 (912) 345-67-89", "+7 912 345 67 89", "9123456789", "79123456789"]
)
def test_phone_search_key_ignores_format_and_country_code(number) -> None:
    assert phone_search_key(number) == "9123456789"


@pytest.mark.django_db
def test_client_belongs_to_default_clinic() -> None:
    client = make_client("Иванова")

    assert client.clinic.name == "Клиника"


@pytest.mark.django_db
def test_last_name_is_required() -> None:
    with pytest.raises(ClientError, match="фамилию"):
        make_client("   ")


@pytest.mark.django_db
def test_first_phone_becomes_primary_and_only_one_primary() -> None:
    client = Client(last_name="Иванова")
    services.save_client(
        client, [{"number": "111-22-33"}, {"number": "+7 900 000-00-01", "is_primary": True}]
    )
    services.save_client(client, [{"number": "111-22-33"}, {"number": "222-33-44"}])

    assert [(p.number, p.is_primary) for p in client.phones.all()] == [
        ("111-22-33", True),
        ("222-33-44", False),
    ]


@pytest.mark.django_db
def test_invalid_phone_is_rejected() -> None:
    with pytest.raises(ClientError, match="номер телефона"):
        make_client("Иванова", phones=["12"])


@pytest.mark.django_db
def test_street_must_belong_to_city() -> None:
    moscow, kazan = City.objects.create(name="Москва"), City.objects.create(name="Казань")
    street = Street.objects.create(name="Баумана", city=kazan)

    with pytest.raises(ClientError, match="Улица"):
        make_client("Иванова", city=moscow, street=street)


@pytest.mark.django_db
def test_phone_key_is_filled_even_when_saved_directly() -> None:
    client = make_client("Иванова")

    phone = ClientPhone.objects.create(client=client, number="8 (912) 345-67-89")

    assert phone.search_key == "9123456789"


@pytest.mark.django_db
def test_set_status() -> None:
    client = make_client("Иванова")

    services.set_status(client, Client.Status.INACTIVE)

    assert Client.objects.get(pk=client.pk).status == "inactive"
    with pytest.raises(ClientError):
        services.set_status(client, "archived")


@pytest.mark.django_db
def test_search_by_name_parts_and_phone() -> None:
    anna = make_client("Иванова", "Анна", phones=["+7 912 345-67-89"])
    make_client("Петров", "Иван", phones=["8 900 111-22-33"])

    def found(text):
        return list(services.search_clients(Client.objects.all(), text))

    assert found("иванова") == [anna]
    assert found("анна 4567") == [anna]
    assert found("89123456789") == [anna]
    assert {c.last_name for c in found("иван")} == {"Иванова", "Петров"}


@pytest.mark.django_db
def test_search_by_journal_number_and_discount_card() -> None:
    anna = make_client("Иванова", journal_number="К-15", discount_card="000777")

    assert list(services.search_clients(Client.objects.all(), "к-15")) == [anna]
    assert list(services.search_clients(Client.objects.all(), "000777")) == [anna]


@pytest.mark.django_db
def test_duplicates_by_phone_in_any_format() -> None:
    anna = make_client("Иванова", "Анна", phones=["+7 (912) 345-67-89"])

    found = services.find_duplicates(last_name="Смирнова", phones=["89123456789"])

    assert [d["id"] for d in found] == [str(anna.pk)]
    assert found[0]["reasons"] == ["phone"]


@pytest.mark.django_db
def test_duplicates_by_similar_name_including_typos_and_inactive() -> None:
    anna = make_client("Иванова", "Анна", status=Client.Status.INACTIVE)
    make_client("Петрова", "Мария")

    found = services.find_duplicates(last_name="Иваноова", first_name="Анна")

    assert [d["full_name"] for d in found] == ["Иванова Анна"]
    assert found[0]["status"] == "inactive"
    assert found[0]["id"] == str(anna.pk)


@pytest.mark.django_db
def test_duplicates_exclude_the_client_itself() -> None:
    anna = make_client("Иванова", "Анна", phones=["+7 912 345-67-89"])

    assert (
        services.find_duplicates(
            last_name="Иванова", first_name="Анна", phones=["+7 912 345-67-89"], exclude_id=anna.pk
        )
        == []
    )


@pytest.mark.django_db
def test_phone_match_is_listed_first() -> None:
    make_client("Иванова", "Анна")
    by_phone = make_client("Сидоров", phones=["8 900 000 00 01"])

    found = services.find_duplicates(last_name="Иванова", first_name="Анна", phones=["9000000001"])

    assert found[0]["id"] == str(by_phone.pk)
