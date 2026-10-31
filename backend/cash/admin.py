from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from cash.models import CashOperation, CashRegister, CashShift, Payment
from core.admin import DirectoryAdmin


@admin.register(CashRegister)
class CashRegisterAdmin(DirectoryAdmin):
    list_display = ("name", "kind", "responsible", "is_active")


@admin.register(Payment)
class PaymentAdmin(SimpleHistoryAdmin):  # type: ignore[misc]
    list_display = (
        "number",
        "date",
        "client",
        "cash_received",
        "change_given",
        "card_amount",
        "status",
    )
    raw_id_fields = ("client",)


@admin.register(CashOperation)
class CashOperationAdmin(SimpleHistoryAdmin):  # type: ignore[misc]
    list_display = ("number", "date", "kind", "register", "amount", "status")


@admin.register(CashShift)
class CashShiftAdmin(SimpleHistoryAdmin):  # type: ignore[misc]
    list_display = ("register", "opened_at", "closed_at", "income", "expense", "closing_balance")
