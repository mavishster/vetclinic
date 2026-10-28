"""Ядро: публичный вход модуля.

Отвечает за: базовые модели, документы, журнал движений, справочники, права,
аудит, нумерацию, печать.

Другие модули обращаются к модулю только через функции этого файла.
Бизнес-правила живут здесь, а не в моделях и не в API (ENGINEERING.md).
"""

from typing import TypedDict

from django.db import DatabaseError, connection


class HealthStatus(TypedDict):
    status: str
    database: bool


def health() -> HealthStatus:
    """Проверка работоспособности: отвечает ли приложение и доступна ли база."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        database_ok = True
    except DatabaseError:
        database_ok = False
    return {"status": "ok" if database_ok else "degraded", "database": database_ok}
