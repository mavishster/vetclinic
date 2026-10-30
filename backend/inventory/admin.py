from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from core.admin import DirectoryAdmin
from inventory.models import Batch, Manufacturer, StockDocument, StockLine, Warehouse

admin.site.register(Manufacturer, DirectoryAdmin)


@admin.register(Warehouse)
class WarehouseAdmin(DirectoryAdmin):
    list_display = ("name", "kind", "responsible", "is_active")


class LineInline(admin.TabularInline):  # type: ignore[type-arg]
    model = StockLine
    extra = 0
    readonly_fields = ("qty_base", "batch")


@admin.register(StockDocument)
class StockDocumentAdmin(SimpleHistoryAdmin):  # type: ignore[misc]
    list_display = ("number", "kind", "date", "warehouse", "status")
    list_filter = ("kind", "status", "warehouse")
    inlines = [LineInline]


@admin.register(Batch)
class BatchAdmin(SimpleHistoryAdmin):  # type: ignore[misc]
    list_display = ("item", "series", "expiry_date", "cost_per_base", "received_at")
    search_fields = ("series", "item__name")
