from django.urls import path
from rest_framework.routers import DefaultRouter

from clients.api import clients, contracts, pets, signing, views

router = DefaultRouter()
router.register("species", views.SpeciesViewSet, basename="species")
router.register("breeds", views.BreedViewSet, basename="breed")
router.register("cities", views.CityViewSet, basename="city")
router.register("streets", views.StreetViewSet, basename="street")
router.register("client-types", views.ClientTypeViewSet, basename="client-type")
router.register("client-sources", views.ClientSourceViewSet, basename="client-source")
router.register("colors", views.ColorViewSet, basename="color")
router.register("clients", clients.ClientViewSet, basename="client")
router.register("pets", pets.PetViewSet, basename="pet")
router.register("contracts", contracts.ContractViewSet, basename="contract")
router.register("signing-stations", signing.SigningStationViewSet, basename="signing-station")
router.register("signatures", signing.SignatureRequestViewSet, basename="signature")

urlpatterns = [
    path("signing/current/", signing.StationCurrentView.as_view(), name="signing-current"),
    path("signing/sign/", signing.StationSignView.as_view(), name="signing-sign"),
    *router.urls,
]
