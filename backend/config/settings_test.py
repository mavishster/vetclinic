"""Настройки для тестов: основные + тестовое приложение с примерами документа и журнала.

Тестовое приложение проверяет механики ядра (документ, журнал движений)
на конкретных моделях, не завися от модулей верхних уровней.
"""

from config.settings import *  # noqa: F403
from config.settings import INSTALLED_APPS

INSTALLED_APPS = [*INSTALLED_APPS, "core.tests.testapp"]

# В тестах фоновые задачи выполняются сразу, без отдельного процесса.
Q_CLUSTER = {**Q_CLUSTER, "sync": True}  # noqa: F405
