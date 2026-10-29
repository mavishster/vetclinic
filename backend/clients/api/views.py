from clients.models import Breed, City, ClientSource, ClientType, Species, Street
from core.api.directories import DirectoryViewSet


class SpeciesViewSet(DirectoryViewSet):
    model = Species


class BreedViewSet(DirectoryViewSet):
    model = Breed
    extra_fields = ("species",)
    filter_fields = ("species",)


class CityViewSet(DirectoryViewSet):
    model = City


class StreetViewSet(DirectoryViewSet):
    model = Street
    extra_fields = ("city",)
    filter_fields = ("city",)


class ClientTypeViewSet(DirectoryViewSet):
    model = ClientType


class ClientSourceViewSet(DirectoryViewSet):
    model = ClientSource
