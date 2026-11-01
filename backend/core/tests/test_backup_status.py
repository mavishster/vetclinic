import json
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from core import services


def stamp(hours_ago: float) -> str:
    return (timezone.now() - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%S%z")


@pytest.fixture
def backups(tmp_path, settings):
    settings.BACKUP_DIR = tmp_path
    return tmp_path


def write(folder, name, data) -> None:
    (folder / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


def test_fresh_backup_and_check_ok(backups) -> None:
    write(backups, "backup", {"ok": True, "at": stamp(3), "name": "vetclinic-x"})
    write(backups, "restore_check", {"ok": True, "at": stamp(2), "clients": 5})

    status = services.backup_status()

    assert status["ok"] is True and status["problems"] == []


@pytest.mark.parametrize(
    ("backup", "check", "problem"),
    [
        (None, None, "ещё нет"),
        ({"ok": False, "at": "2026-11-01T02:00:00+0000"}, None, "не удалась"),
        ({"ok": True, "at": "OLD"}, None, "больше"),
        ({"ok": True, "at": "NOW"}, {"ok": False}, "восстановления"),
    ],
)
def test_problems_are_reported(backups, backup, check, problem) -> None:
    if backup:
        backup = {
            **backup,
            "at": {"OLD": stamp(50), "NOW": stamp(1)}.get(backup["at"], backup["at"]),
        }
        write(backups, "backup", backup)
    if check:
        write(backups, "restore_check", check)

    status = services.backup_status()

    assert status["ok"] is False
    assert problem in " ".join(status["problems"])


def test_api_only_for_admins(backups, db) -> None:
    plain = APIClient()
    plain.force_authenticate(get_user_model().objects.create_user(username="u", password="x"))
    admin = APIClient()
    admin.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))

    assert plain.get("/api/core/backup-status/").status_code == 403
    assert admin.get("/api/core/backup-status/").json()["ok"] is False


def test_not_configured_on_developer_computer(tmp_path, settings) -> None:
    settings.BACKUP_DIR = tmp_path / "нет-такой-папки"

    assert services.backup_status()["configured"] is False
