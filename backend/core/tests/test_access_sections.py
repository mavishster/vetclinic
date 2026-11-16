"""Разделы прав «Отчёты», «Выручка», «Профилактика» и перенос прежних прав."""

import importlib

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from rest_framework.test import APIClient

from core import services

SECTIONS = {
    "reports": "core.reportsaccess",
    "revenue": "core.revenueaccess",
    "prevention": "core.preventionreportaccess",
}


def _user(*perms: str):
    user = get_user_model().objects.create_user(username=f"u{len(perms)}{perms[:1]}", password="x")
    group = Group.objects.create(name=f"g{user.pk}")
    for code in perms:
        app_label, codename = code.split(".")
        group.permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    user.groups.add(group)
    return user


def _api(user) -> APIClient:
    api = APIClient()
    api.force_authenticate(user)
    return api


def test_sections_are_top_level_rows_with_only_view(db) -> None:
    modules = {m["code"]: m for m in services.permission_modules()}

    for code, entity in SECTIONS.items():
        (row,) = modules[code]["entities"]
        assert row["code"] == entity
        assert row["actions"] == ["view"]
    assert {m["title"] for m in modules.values()} >= {"Отчёты", "Выручка", "Профилактика"}
    # Раздел доступа не дублируется внутри «Администрирования».
    assert not {e["code"] for e in modules["core"]["entities"]} & set(SECTIONS.values())
    # VetManager — только особое право, строк в таблице у него нет.
    assert modules["vetmanager"]["entities"] == []


def test_section_view_is_granted_through_role(db) -> None:
    role = Group.objects.create(name="Бухгалтер")

    services.set_entity_permissions(role, "core.revenueaccess", {"view", "edit", "delete"})

    assert services.entity_actions(role, "core.revenueaccess") == {"view"}
    user = get_user_model().objects.create_user(username="acc", password="x")
    user.groups.add(role)
    assert user.has_perm("core.view_revenueaccess")
    assert not user.has_perm("core.view_reportsaccess")


@pytest.mark.parametrize(
    ("url", "need"),
    [
        ("/api/billing/reports/sales/", "billing.view_invoice"),
        ("/api/cash/reports/money/", "cash.view_payment"),
        ("/api/inventory/reports/turnover/", "inventory.view_stockmovement"),
        ("/api/inventory/reports/warehouses/", "inventory.view_stockmovement"),
    ],
)
def test_reports_need_section_and_data_right(db, url: str, need: str) -> None:
    assert _api(_user(need)).get(url).status_code == 403
    assert _api(_user("core.view_reportsaccess")).get(url).status_code == 403
    assert _api(_user(need, "core.view_reportsaccess")).get(url).status_code == 200


def test_revenue_report_needs_only_revenue_section(db) -> None:
    url = "/api/billing/reports/performers/"

    assert _api(_user("billing.view_invoice")).get(url).status_code == 403
    assert _api(_user("core.view_revenueaccess")).get(url).status_code == 200


def test_prevention_report_needs_section_but_pet_history_does_not(db) -> None:
    only_records = _api(_user("medical.view_prevention"))
    section = _api(_user("core.view_preventionreportaccess"))

    assert only_records.get("/api/medical/preventions/report/?mode=done").status_code == 403
    assert section.get("/api/medical/preventions/report/?mode=done").status_code == 200
    assert only_records.get("/api/medical/preventions/").status_code != 403  # нужен ?pet=


def test_migration_gives_new_rights_to_roles_with_old_ones(db) -> None:
    migration = importlib.import_module("core.migrations.0019_grant_access_sections")
    cashier = _user("billing.view_invoice").groups.get()
    keeper = _user("inventory.view_stockmovement").groups.get()
    doctor = _user("medical.view_prevention").groups.get()
    nobody = _user("clients.view_client").groups.get()

    migration.grant(apps, None)

    def codes(group: Group) -> set[str]:
        return {
            p.codename
            for p in group.permissions.filter(content_type__app_label="core")
            if p.codename.endswith("access")
        }

    assert codes(cashier) == {"view_reportsaccess", "view_revenueaccess"}
    assert codes(keeper) == {"view_reportsaccess"}
    assert codes(doctor) == {"view_preventionreportaccess"}
    assert codes(nobody) == set()
