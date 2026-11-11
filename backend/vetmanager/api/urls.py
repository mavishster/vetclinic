from django.urls import path

from vetmanager.api import views

urlpatterns = [
    path("status/", views.StatusView.as_view(), name="vetmanager-status"),
    path("probe/", views.ProbeView.as_view(), name="vetmanager-probe"),
    path("run/", views.RunStepView.as_view(), name="vetmanager-run"),
]
