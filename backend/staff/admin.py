from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from core.admin import DirectoryAdmin
from staff.models import Employee, IntervalTemplate, IntervalType, Position, WorkInterval

admin.site.register(Position, DirectoryAdmin)
admin.site.register(IntervalType, DirectoryAdmin)
admin.site.register(IntervalTemplate, DirectoryAdmin)


@admin.register(Employee)
class EmployeeAdmin(SimpleHistoryAdmin):  # type: ignore[misc]
    list_display = ("user", "position", "phone", "in_schedule")
    list_filter = ("position", "in_schedule")


@admin.register(WorkInterval)
class WorkIntervalAdmin(SimpleHistoryAdmin):  # type: ignore[misc]
    list_display = ("user", "start", "end", "interval_type")
    list_filter = ("interval_type", "user")
