from django.urls import path
from rest_framework.routers import DefaultRouter

from catalog.api import importing, views

router = DefaultRouter()
router.register("units", views.UnitViewSet, basename="unit")
router.register("groups", views.ItemGroupViewSet, basename="item-group")
router.register("items", views.ItemViewSet, basename="item")

urlpatterns = [
    path("import/preview/", importing.ImportPreview.as_view(), name="catalog-import-preview"),
    path("import/commit/", importing.ImportCommit.as_view(), name="catalog-import-commit"),
    path("import/template/", importing.ImportTemplate.as_view(), name="catalog-import-template"),
    *router.urls,
]
