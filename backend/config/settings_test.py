"""Настройки для тестов: основные + тестовое приложение с примерами документа и журнала.

Тестовое приложение проверяет механики ядра (документ, журнал движений)
на конкретных моделях, не завися от модулей верхних уровней.
"""

from config.settings import *  # noqa: F403
from config.settings import INSTALLED_APPS

INSTALLED_APPS = [*INSTALLED_APPS, "core.tests.testapp"]
