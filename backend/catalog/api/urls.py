from rest_framework.routers import DefaultRouter

from catalog.api import views

router = DefaultRouter()
router.register("units", views.UnitViewSet, basename="unit")
router.register("groups", views.ItemGroupViewSet, basename="item-group")
router.register("items", views.ItemViewSet, basename="item")

urlpatterns = router.urls
