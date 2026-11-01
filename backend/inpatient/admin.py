from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from core.admin import DirectoryAdmin
from inpatient.models import Hospitalization, Ward


@admin.register(Ward)
class WardAdmin(DirectoryAdmin):
    list_display = ("name", "kind", "places", "daily_item", "is_active")


@admin.register(Hospitalization)
class HospitalizationAdmin(SimpleHistoryAdmin):  # type: ignore[misc]
    list_display = ("pet", "ward", "place", "doctor", "admitted_at", "discharged_at", "status")
    list_filter = ("status", "ward")
    raw_id_fields = ("pet", "client", "visit")
