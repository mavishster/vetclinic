from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from core.admin import DirectoryAdmin
from medical.models import Diagnosis, Prevention, PreventionType, Visit, VisitResult

admin.site.register(Diagnosis, DirectoryAdmin)
admin.site.register(VisitResult, DirectoryAdmin)


@admin.register(PreventionType)
class PreventionTypeAdmin(DirectoryAdmin):
    list_display = ("name", "kind", "repeat_days", "is_active")


@admin.register(Visit)
class VisitAdmin(SimpleHistoryAdmin):  # type: ignore[misc]
    list_display = ("date", "pet", "client", "doctor", "purpose")
    list_filter = ("purpose", "doctor")
    raw_id_fields = ("pet", "client", "appointment")


@admin.register(Prevention)
class PreventionAdmin(SimpleHistoryAdmin):  # type: ignore[misc]
    list_display = ("date", "pet", "type", "item", "next_date", "reminder")
    list_filter = ("type", "reminder")
    raw_id_fields = ("visit", "pet")
