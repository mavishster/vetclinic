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
