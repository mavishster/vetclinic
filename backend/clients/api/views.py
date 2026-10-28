from clients.models import Breed, Species
from core.api.directories import DirectoryViewSet


class SpeciesViewSet(DirectoryViewSet):
    model = Species


class BreedViewSet(DirectoryViewSet):
    model = Breed
    extra_fields = ("species",)
    filter_fields = ("species",)
