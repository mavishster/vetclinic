from rest_framework.routers import DefaultRouter

from inventory.api import views

router = DefaultRouter()
router.register("warehouses", views.WarehouseViewSet, basename="warehouse")
router.register("manufacturers", views.ManufacturerViewSet, basename="manufacturer")
router.register("documents", views.DocumentViewSet, basename="stock-document")
router.register("stock", views.StockViewSet, basename="stock")

urlpatterns = router.urls
