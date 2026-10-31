from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from billing.models import Invoice, InvoiceLine


class LineInline(admin.TabularInline):  # type: ignore[type-arg]
    model = InvoiceLine
    extra = 0
    fields = ("item", "item_unit", "quantity", "price", "discount", "amount", "performer", "cost")
    readonly_fields = fields


@admin.register(Invoice)
class InvoiceAdmin(SimpleHistoryAdmin):  # type: ignore[misc]
    list_display = ("number", "date", "client", "total", "status")
    list_filter = ("status",)
    search_fields = ("number", "client__last_name")
    raw_id_fields = ("client", "pet", "appointment", "visit")
    inlines = [LineInline]
