from rest_framework.routers import DefaultRouter

from clients.api import views

router = DefaultRouter()
router.register("species", views.SpeciesViewSet, basename="species")
router.register("breeds", views.BreedViewSet, basename="breed")

urlpatterns = router.urls
