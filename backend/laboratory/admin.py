from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from core.admin import DirectoryAdmin
from laboratory.models import Analyte, AnalyteNorm, LabResult, LabValue


class NormInline(admin.TabularInline):  # type: ignore[type-arg]
    model = AnalyteNorm
    extra = 0


@admin.register(Analyte)
class AnalyteAdmin(DirectoryAdmin):
    list_display = ("code", "name", "unit", "group", "is_active")
    search_fields = ("code", "name")
    inlines = [NormInline]


class ValueInline(admin.TabularInline):  # type: ignore[type-arg]
    model = LabValue
    extra = 0


@admin.register(LabResult)
class LabResultAdmin(SimpleHistoryAdmin):  # type: ignore[misc]
    list_display = ("received_at", "analysis", "device", "pet", "code_entered", "status")
    list_filter = ("status", "device")
    raw_id_fields = ("visit", "pet")
    inlines = [ValueInline]
