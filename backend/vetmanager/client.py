"""Обращение к API VetManager: адрес и ключ — из настроек (.env).

VETMANAGER_URL — адрес клиники (https://клиника.vetmanager.cloud),
VETMANAGER_API_KEY — ключ REST API. Данные только читаются.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from django.conf import settings

PAGE_SIZE = 500
TIMEOUT = 120


class VetManagerError(Exception):
    """Не удалось получить данные. Текст — для пользователя."""


def is_configured() -> bool:
    return bool(settings.VETMANAGER_URL and settings.VETMANAGER_API_KEY)


def _request(path: str, params: dict[str, Any]) -> dict[str, Any]:
    if not is_configured():
        raise VetManagerError(
            "Не заданы адрес и ключ VetManager: добавьте VETMANAGER_URL "
            "и VETMANAGER_API_KEY в .env."
        )
    url = f"{settings.VETMANAGER_URL.rstrip('/')}/rest/api/{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url, headers={"X-REST-API-KEY": settings.VETMANAGER_API_KEY, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 — адрес из настроек
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        hint = (
            "Проверьте ключ REST API." if error.code in (401, 403) else "Проверьте адрес клиники."
        )
        raise VetManagerError(f"VetManager ответил {error.code}. {hint}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise VetManagerError(f"Не удалось связаться с VetManager: {error}") from error
    except json.JSONDecodeError as error:
        raise VetManagerError("VetManager вернул не JSON — проверьте адрес клиники.") from error
    if not payload.get("success", True):
        raise VetManagerError(str(payload.get("message") or "VetManager вернул ошибку."))
    data = payload.get("data")
    if not isinstance(data, dict):
        raise VetManagerError("Неожиданный ответ VetManager: нет раздела data.")
    return data


def _rows(data: dict[str, Any], model: str) -> list[dict[str, Any]]:
    """Строки ответа: VetManager кладёт их в раздел с именем модели в нижнем регистре."""
    for key, value in data.items():
        if key != "totalCount" and isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return list(data.get(model.lower(), []))


def fetch(
    model: str, params: dict[str, Any] | None = None, limit: int | None = None
) -> list[dict[str, Any]]:
    """Все записи модели (Client, Pet, Good…), страницами по PAGE_SIZE."""
    collected: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = min(PAGE_SIZE, limit - len(collected)) if limit else PAGE_SIZE
        data = _request(model, {**(params or {}), "limit": page, "offset": offset})
        rows = _rows(data, model)
        collected.extend(rows)
        total = int(data.get("totalCount") or 0)
        offset += len(rows)
        if not rows or (limit and len(collected) >= limit) or offset >= total:
            break
    return collected


def sample(model: str, count: int = 2) -> dict[str, Any]:
    """Сколько записей и как выглядят первые — чтобы сверить поля с реальным аккаунтом."""
    data = _request(model, {"limit": count, "offset": 0})
    rows = _rows(data, model)
    return {
        "model": model,
        "total": int(data.get("totalCount") or 0),
        "fields": sorted(rows[0]) if rows else [],
        "rows": rows,
    }
