import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from core import services


@pytest.fixture
def role(db):
    return Group.objects.create(name="Регистратор")


def test_module_actions_grant_standard_permissions(role) -> None:
    services.set_module_permissions(role, "clients", {"view", "edit"})
    user = get_user_model().objects.create_user(username="u", password="x")
    user.groups.add(role)

    assert user.has_perm("clients.view_species")
    assert user.has_perm("clients.add_breed")
    assert user.has_perm("clients.change_breed")
    assert not user.has_perm("clients.delete_breed")


def test_module_actions_are_replaced_not_added(role) -> None:
    services.set_module_permissions(role, "clients", {"view", "edit", "delete"})

    services.set_module_permissions(role, "clients", {"view"})

    assert services.module_actions(role, "clients") == {"view"}


def test_history_models_are_not_part_of_module_permissions(role) -> None:
    services.set_module_permissions(role, "clients", {"view", "edit", "delete"})

    codenames = set(role.permissions.values_list("codename", flat=True))
    assert not any("historical" in code for code in codenames)


def test_unknown_action_is_rejected(role) -> None:
    with pytest.raises(ValueError, match="Неизвестные действия: approve"):
        services.set_module_permissions(role, "clients", {"approve"})


def test_entity_permissions_are_independent(role) -> None:
    services.set_entity_permissions(role, "core.printtemplate", {"view", "edit"})
    user = get_user_model().objects.create_user(username="designer", password="x")
    user.groups.add(role)

    assert user.has_perm("core.change_printtemplate")
    assert not user.has_perm("core.view_user")
    assert not user.has_perm("core.view_clinic")


def test_module_actions_are_common_to_all_entities(role) -> None:
    services.set_entity_permissions(role, "clients.species", {"view", "edit"})
    services.set_entity_permissions(role, "clients.breed", {"view"})

    assert services.module_actions(role, "clients") == {"view"}


def test_matrix_shows_entities_and_hides_service_tables() -> None:
    modules = {m["code"]: m for m in services.permission_modules()}

    core_entities = [e["code"] for e in modules["core"]["entities"]]
    assert modules["core"]["title"] == "Администрирование"
    assert core_entities == ["core.user", "core.clinic", "core.printtemplate", "auth.group"]
    assert [e["title"] for e in modules["clients"]["entities"]] == ["Виды животных", "Породы"]


def test_unknown_entity_is_rejected(role) -> None:
    with pytest.raises(ValueError, match="Неизвестный раздел"):
        services.set_entity_permissions(role, "core.documentcounter", {"view"})
