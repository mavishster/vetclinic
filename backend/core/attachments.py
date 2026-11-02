"""Файлы: какие записи можно снабжать файлами, загрузка, проверки.

Модуль регистрирует свои записи в apps.py → ready():

    from core.attachments import register_owner
    register_owner("clients.client")
"""

from typing import Any

from django.apps import apps
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.files import File

from core.models import Attachment, FileCategory

_OWNERS: set[str] = set()


class AttachmentError(Exception):
    """Файл нельзя прикрепить. Текст — для пользователя."""


def register_owner(label: str) -> None:
    """Разрешить прикреплять файлы к записям модели «приложение.модель»."""
    _OWNERS.add(label.lower())


def owner_content_type(label: str) -> ContentType:
    if label.lower() not in _OWNERS:
        raise AttachmentError(f"К записям «{label}» нельзя прикреплять файлы.")
    return ContentType.objects.get_for_model(apps.get_model(label))


def attach(
    owner_label: str,
    owner_id: Any,
    file: "File[Any]",  # загруженный файл или созданный системой (ContentFile)
    name: str = "",
    category: FileCategory | None = None,
) -> Attachment:
    """Прикрепить файл к записи. Проверяет, что запись существует, и размер файла."""
    owner_type = owner_content_type(owner_label)
    model = owner_type.model_class()
    if model is None or not model._default_manager.filter(pk=owner_id).exists():
        raise AttachmentError("Запись, к которой прикрепляется файл, не найдена.")
    limit = settings.ATTACHMENT_MAX_MB * 1024 * 1024
    if file.size and file.size > limit:
        raise AttachmentError(f"Файл больше {settings.ATTACHMENT_MAX_MB} МБ.")
    return Attachment.objects.create(
        owner_type=owner_type,
        owner_id=owner_id,
        file=file,
        name=(name or file.name or "файл").strip()[:255],
        category=category,
        size=file.size or 0,
        content_type=getattr(file, "content_type", "") or "",
    )


def attachments_of(owner_label: str, owner_id: Any) -> Any:
    return Attachment.objects.filter(owner_type=owner_content_type(owner_label), owner_id=owner_id)
