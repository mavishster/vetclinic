"""Общие настройки тестов. Фикстуры для всех модулей добавляются здесь."""

import pytest


@pytest.fixture(autouse=True)
def _clinic_time_zone(settings):  # type: ignore[no-untyped-def]
    """Тесты считают время по Бишкеку (UTC+6) — независимо от TIME_ZONE в .env компьютера."""
    settings.TIME_ZONE = "Asia/Bishkek"
