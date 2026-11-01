from django.urls import path
from rest_framework.routers import DefaultRouter

from inventory.api import views

router = DefaultRouter()
router.register("warehouses", views.WarehouseViewSet, basename="warehouse")
router.register("manufacturers", views.ManufacturerViewSet, basename="manufacturer")
router.register("documents", views.DocumentViewSet, basename="stock-document")
router.register("stock", views.StockViewSet, basename="stock")
router.register("min-stock", views.MinStockViewSet, basename="min-stock")

urlpatterns = [
    path("labels/", views.LabelsView.as_view(), name="stock-labels"),
    path("reports/turnover/", views.TurnoverReportView.as_view(), name="report-turnover"),
    path("import/<str:step>/", views.StockImportView.as_view(), name="stock-import"),
    *router.urls,
]
