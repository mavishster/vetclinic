from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from reminders.models import Reminder


@admin.register(Reminder)
class ReminderAdmin(SimpleHistoryAdmin):  # type: ignore[misc]
    list_display = ("due_date", "client", "pet", "kind", "text", "status", "attempts")
    list_filter = ("kind", "status")
    raw_id_fields = ("client", "pet")
