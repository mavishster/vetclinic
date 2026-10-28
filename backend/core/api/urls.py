from django.urls import path
from rest_framework.routers import DefaultRouter

from core.api import views
from core.api.printing import PrintTemplateViewSet

router = DefaultRouter()
router.register("print-templates", PrintTemplateViewSet, basename="print-template")

urlpatterns = [
    path("health/", views.health, name="core-health"),
    path("me/", views.me, name="core-me"),
    path("me/pin/", views.set_my_pin, name="core-me-pin"),
    *router.urls,
]
