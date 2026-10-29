from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from core.admin import DirectoryAdmin
from medical.models import Diagnosis, Vaccination, Visit, VisitResult

admin.site.register(Diagnosis, DirectoryAdmin)
admin.site.register(VisitResult, DirectoryAdmin)


@admin.register(Visit)
class VisitAdmin(SimpleHistoryAdmin):  # type: ignore[misc]
    list_display = ("date", "pet", "client", "doctor", "purpose")
    list_filter = ("purpose", "doctor")
    raw_id_fields = ("pet", "client", "appointment")


@admin.register(Vaccination)
class VaccinationAdmin(SimpleHistoryAdmin):  # type: ignore[misc]
    list_display = ("date", "pet", "vaccine", "next_date", "reminder")
    raw_id_fields = ("visit", "pet")
