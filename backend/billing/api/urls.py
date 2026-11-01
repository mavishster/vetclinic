from django.urls import path
from rest_framework.routers import DefaultRouter

from billing.api import views

router = DefaultRouter()
router.register("invoices", views.InvoiceViewSet, basename="invoice")

urlpatterns = [
    path("reports/performers/", views.PerformersReport.as_view(), name="report-performers"),
    path("reports/sales/", views.SalesReportView.as_view(), name="report-sales"),
    path("reports/top-items/", views.TopItemsReportView.as_view(), name="report-top-items"),
    path("reports/debtors/", views.DebtorsReportView.as_view(), name="report-debtors"),
    *router.urls,
]
