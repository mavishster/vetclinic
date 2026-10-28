from django.contrib import admin

from clients.models import Breed, Species
from core.admin import DirectoryAdmin


@admin.register(Species)
class SpeciesAdmin(DirectoryAdmin):
    pass


@admin.register(Breed)
class BreedAdmin(DirectoryAdmin):
    list_display = ("name", "species", "is_active")
    list_filter = ("species", "is_active")
