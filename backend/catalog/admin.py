from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from catalog.models import Item, ItemGroup, ItemUnit, Unit
from core.admin import DirectoryAdmin

admin.site.register(Unit, DirectoryAdmin)


@admin.register(ItemGroup)
class ItemGroupAdmin(DirectoryAdmin):
    list_display = ("name", "kind", "markup_percent", "show_in_vaccinations", "is_active")
    list_filter = ("kind", "is_active")


class ItemUnitInline(admin.TabularInline):  # type: ignore[type-arg]
    model = ItemUnit
    extra = 0
    fields = ("unit", "ratio", "for_sale", "for_purchase", "pricing", "price", "markup_percent")


@admin.register(Item)
class ItemAdmin(SimpleHistoryAdmin):  # type: ignore[misc]
    list_display = ("name", "kind", "group", "article", "is_active")
    list_filter = ("kind", "group", "is_active")
    search_fields = ("name", "article", "barcode")
    inlines = [ItemUnitInline]
