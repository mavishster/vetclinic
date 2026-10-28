"""Ядро: публичный вход модуля.

Отвечает за: базовые модели, документы, журнал движений, справочники, права,
аудит, нумерацию, печать.

Другие модули обращаются к модулю только через функции этого файла.
Бизнес-правила живут здесь, а не в моделях и не в API (ENGINEERING.md).
"""

from typing import TypedDict

from django.db import DatabaseError, connection

from core.models import Clinic


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


def current_clinic() -> Clinic:
    """Клиника, в которой работает система.

    В первой версии клиника одна (создаётся миграцией). Когда появится второй
    филиал, здесь будет выбор по пользователю или узлу — вызывающий код не изменится.
    """
    clinic = Clinic.objects.order_by("created_at").first()
    if clinic is None:
        raise Clinic.DoesNotExist("Клиника не создана: примените миграции ядра.")
    return clinic
