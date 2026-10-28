"""Общий API справочников (DRY): список с фильтрами, создание, изменение, удаление.

Конкретный справочник объявляет только модель и дополнительные поля:

    class SpeciesViewSet(DirectoryViewSet):
        model = Species
"""

from typing import Any, ClassVar

from django.db.models import QuerySet
from rest_framework import serializers, viewsets

from core.models import Directory


class DirectorySerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    """Проверяет уникальность названия заранее — с понятным сообщением, а не ошибкой базы."""

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Введите название.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        model = self.Meta.model
        name = attrs.get("name", getattr(self.instance, "name", ""))
        scope = {
            field: attrs.get(field, getattr(self.instance, field, None))
            for field in model.unique_within
        }
        duplicates = model.objects.filter(name__iexact=name, **scope)
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError({"name": "Такая запись уже есть в справочнике."})
        return attrs


class DirectoryViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]
    """Фильтры: ?active=true|false, ?search=текст, а также поля из filter_fields.

    DELETE — мягкое удаление; деактивация — PATCH {"is_active": false}.
    """

    model: ClassVar[type[Directory]]
    extra_fields: ClassVar[tuple[str, ...]] = ()
    filter_fields: ClassVar[tuple[str, ...]] = ()
    serializer_base: ClassVar[type[DirectorySerializer]] = DirectorySerializer

    def get_serializer_class(self) -> type[DirectorySerializer]:
        meta = type(
            "Meta",
            (),
            {"model": self.model, "fields": ["id", "name", "is_active", *self.extra_fields]},
        )
        return type(f"{self.model.__name__}Serializer", (self.serializer_base,), {"Meta": meta})

    def get_queryset(self) -> QuerySet[Directory]:
        queryset = self.model.objects.all()
        params = self.request.query_params
        if (active := params.get("active")) is not None:
            queryset = queryset.filter(is_active=active.lower() in {"1", "true", "yes"})
        if search := params.get("search", "").strip():
            queryset = queryset.filter(name__icontains=search)
        for field in self.filter_fields:
            if value := params.get(field):
                queryset = queryset.filter(**{field: value})
        return queryset
