from rest_framework.routers import DefaultRouter

from inpatient.api import views

router = DefaultRouter()
router.register("wards", views.WardViewSet, basename="ward")
router.register("hospitalizations", views.HospitalizationViewSet, basename="hospitalization")

urlpatterns = router.urls
