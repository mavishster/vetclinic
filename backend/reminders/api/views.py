"""API напоминаний: список для обзвона, итог звонка, история клиента."""

from typing import Any

from django.db.models import QuerySet
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from reminders import services
from reminders.models import Reminder


class ReminderSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    client_name = serializers.CharField(source="client.full_name", read_only=True)
    pet_name = serializers.CharField(source="pet.name", read_only=True, default="")
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    phone = serializers.SerializerMethodField()
    overdue = serializers.SerializerMethodField()
    contacted_by_name = serializers.CharField(
        source="contacted_by.short_name", read_only=True, default=""
    )

    class Meta:
        model = Reminder
        fields = [
            "id", "kind", "kind_label", "client", "client_name", "phone", "pet", "pet_name",
            "due_date", "overdue", "text", "status", "status_label", "attempts", "last_contact_at",
            "contacted_by_name", "note",
        ]  # fmt: skip
        read_only_fields = fields

    def get_phone(self, reminder: Reminder) -> str:
        return next((p.number for p in reminder.client.phones.all()), "")

    def get_overdue(self, reminder: Reminder) -> bool:
        return reminder.due_date < timezone.localdate()


class ReminderViewSet(viewsets.ReadOnlyModelViewSet):  # type: ignore[type-arg]
    """Напоминания. Список для обзвона (по умолчанию): ?kind=; история клиента: ?client=.

    Перед показом списка напоминания собираются заново — список всегда свежий.
    POST /{id}/mark/ {"status": "no_answer|done|declined|booked|open", "note": "…"}.
    """

    serializer_class = ReminderSerializer
    queryset = Reminder.objects.all()

    def get_queryset(self) -> QuerySet[Reminder]:
        params = self.request.query_params
        if client := params.get("client"):
            return (
                services.for_client(client)
                .select_related("pet", "client", "contacted_by")
                .prefetch_related("client__phones")
            )
        return services.to_call(params.get("kind") or None).select_related("contacted_by")

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if not request.query_params.get("client"):
            services.refresh()
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=["get"])
    def count(self, request: Request) -> Response:
        services.refresh()
        return Response({"to_call": services.count_to_call()})

    @action(detail=True, methods=["post"])
    def mark(self, request: Request, pk: str | None = None) -> Response:
        reminder = self.get_object()
        try:
            services.mark(
                reminder, request.data.get("status", ""), request.user, request.data.get("note", "")
            )
        except services.ReminderError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        return Response(self.get_serializer(reminder).data)
