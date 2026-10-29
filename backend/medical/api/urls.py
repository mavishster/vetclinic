from rest_framework.routers import DefaultRouter

from medical.api import views

router = DefaultRouter()
router.register("diagnoses", views.DiagnosisViewSet, basename="diagnosis")
router.register("results", views.VisitResultViewSet, basename="visit-result")
router.register("visits", views.VisitViewSet, basename="visit")
router.register("vaccinations", views.PetVaccinationsViewSet, basename="vaccination")
router.register("vaccines", views.VaccinesViewSet, basename="vaccine")

urlpatterns = router.urls
