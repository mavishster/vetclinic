from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from core.admin import DirectoryAdmin
from scheduling.models import Appointment, VisitPurpose


@admin.register(VisitPurpose)
class VisitPurposeAdmin(DirectoryAdmin):
    list_display = ("name", "kind", "duration_minutes", "show_in_portal", "is_active")


@admin.register(Appointment)
class AppointmentAdmin(SimpleHistoryAdmin):  # type: ignore[misc]
    list_display = ("start", "client", "pet", "doctor", "purpose", "status")
    list_filter = ("status", "doctor", "purpose")
    raw_id_fields = ("client", "pet", "parent")
