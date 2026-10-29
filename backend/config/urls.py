"""Корневые маршруты. Каждый модуль подключает свои маршруты под /api/<модуль>/."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/core/", include("core.api.urls")),
    path("api/clients/", include("clients.api.urls")),
    path("api/catalog/", include("catalog.api.urls")),
    path("api/staff/", include("staff.api.urls")),
]
