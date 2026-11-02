from django.urls import path
from rest_framework.routers import DefaultRouter

from laboratory.api import views

router = DefaultRouter()
router.register("analytes", views.AnalyteViewSet, basename="analyte")
router.register("results", views.ResultViewSet, basename="lab-result")

urlpatterns = [path("ingest/", views.IngestView.as_view(), name="lab-ingest"), *router.urls]
