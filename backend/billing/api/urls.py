from django.urls import path
from rest_framework.routers import DefaultRouter

from billing.api import views

router = DefaultRouter()
router.register("invoices", views.InvoiceViewSet, basename="invoice")

urlpatterns = [
    path("reports/performers/", views.PerformersReport.as_view(), name="report-performers"),
    *router.urls,
]
