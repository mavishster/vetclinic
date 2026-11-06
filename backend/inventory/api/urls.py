from django.urls import path
from rest_framework.routers import DefaultRouter

from inventory.api import departments, views

router = DefaultRouter()
router.register("warehouses", views.WarehouseViewSet, basename="warehouse")
router.register("departments", views.DepartmentViewSet, basename="department")
router.register("manufacturers", views.ManufacturerViewSet, basename="manufacturer")
router.register("documents", views.DocumentViewSet, basename="stock-document")
router.register("stock", views.StockViewSet, basename="stock")
router.register("min-stock", views.MinStockViewSet, basename="min-stock")

urlpatterns = [
    path("labels/", views.LabelsView.as_view(), name="stock-labels"),
    path("reports/turnover/", views.TurnoverReportView.as_view(), name="report-turnover"),
    path("transfer/", views.TransferView.as_view(), name="stock-transfer"),
    path(
        "department-stock/<str:step>/",
        departments.DepartmentStockView.as_view(),
        name="department-stock",
    ),
    path(
        "reports/departments/",
        departments.DepartmentSummaryView.as_view(),
        name="report-departments",
    ),
    path(
        "reports/department-journal/",
        departments.DepartmentJournalView.as_view(),
        name="report-department-journal",
    ),
    path("reports/warehouses/", views.WarehouseTotalsView.as_view(), name="report-warehouses"),
    path("import/<str:step>/", views.StockImportView.as_view(), name="stock-import"),
    *router.urls,
]
