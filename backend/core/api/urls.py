from django.urls import path

from core.api import views

urlpatterns = [
    path("health/", views.health, name="core-health"),
]
