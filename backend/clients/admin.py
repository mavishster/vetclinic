from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from clients.models import (
    Breed,
    City,
    Client,
    ClientPhone,
    ClientSource,
    ClientType,
    Species,
    Street,
)
from core.admin import DirectoryAdmin


@admin.register(Species)
class SpeciesAdmin(DirectoryAdmin):
    pass


@admin.register(Breed)
class BreedAdmin(DirectoryAdmin):
    list_display = ("name", "species", "is_active")
    list_filter = ("species", "is_active")


@admin.register(City, ClientType, ClientSource)
class ClientDirectoryAdmin(DirectoryAdmin):
    pass


@admin.register(Street)
class StreetAdmin(DirectoryAdmin):
    list_display = ("name", "city", "is_active")
    list_filter = ("city", "is_active")


class PhoneInline(admin.TabularInline):  # type: ignore[type-arg]
    model = ClientPhone
    fields = ("kind", "number", "is_primary", "comment")
    extra = 0


@admin.register(Client)
class ClientAdmin(SimpleHistoryAdmin):  # type: ignore[misc]
    list_display = ("full_name", "city", "status", "in_blacklist")
    list_filter = ("status", "in_blacklist", "city")
    search_fields = ("last_name", "first_name", "middle_name", "phones__search_key")
    inlines = [PhoneInline]
