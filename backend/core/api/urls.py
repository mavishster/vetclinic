from django.urls import path
from rest_framework.routers import DefaultRouter

from core.api import auth, roles, views
from core.api.printing import PrintTemplateViewSet

router = DefaultRouter()
router.register("print-templates", PrintTemplateViewSet, basename="print-template")
router.register("roles", roles.RoleViewSet, basename="role")
router.register("users", roles.UserViewSet, basename="user")

urlpatterns = [
    path("health/", views.health, name="core-health"),
    path("auth/csrf/", auth.csrf, name="core-csrf"),
    path("auth/login/", auth.login_view, name="core-login"),
    path("auth/logout/", auth.logout_view, name="core-logout"),
    path("me/", views.me, name="core-me"),
    path("me/pin/", views.set_my_pin, name="core-me-pin"),
    *router.urls,
]
