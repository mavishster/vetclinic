from rest_framework.routers import DefaultRouter

from medical.api import views

router = DefaultRouter()
router.register("diagnoses", views.DiagnosisViewSet, basename="diagnosis")
router.register("results", views.VisitResultViewSet, basename="visit-result")
router.register("visits", views.VisitViewSet, basename="visit")
router.register("text-templates", views.TextTemplateViewSet, basename="text-template")
router.register("prevention-types", views.PreventionTypeViewSet, basename="prevention-type")
router.register("preventions", views.PreventionViewSet, basename="prevention")

urlpatterns = router.urls
