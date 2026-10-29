from django.urls import path
from rest_framework.routers import DefaultRouter

from scheduling.api import views

router = DefaultRouter()
router.register("purposes", views.PurposeViewSet, basename="purpose")
router.register("appointments", views.AppointmentViewSet, basename="appointment")

urlpatterns = [path("calendar/", views.CalendarView.as_view(), name="calendar"), *router.urls]
