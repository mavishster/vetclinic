from django.urls import path

from vetmanager.api import views

urlpatterns = [
    path("status/", views.StatusView.as_view(), name="vetmanager-status"),
    path("probe/", views.ProbeView.as_view(), name="vetmanager-probe"),
    path("unit-plan/", views.UnitPlanView.as_view(), name="vetmanager-unit-plan"),
    path("doctor-plan/", views.DoctorPlanView.as_view(), name="vetmanager-doctor-plan"),
    path("tidy/", views.TidyView.as_view(), name="vetmanager-tidy"),
    path("run/", views.RunStepView.as_view(), name="vetmanager-run"),
]
