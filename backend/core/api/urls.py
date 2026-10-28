from django.urls import path

from core.api import views

urlpatterns = [
    path("health/", views.health, name="core-health"),
    path("me/", views.me, name="core-me"),
    path("me/pin/", views.set_my_pin, name="core-me-pin"),
]
