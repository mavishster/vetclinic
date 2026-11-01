from django.urls import path
from rest_framework.routers import DefaultRouter

from core.api import attachments, auth, roles, views
from core.api.printing import PrintTemplateViewSet

router = DefaultRouter()
router.register("print-templates", PrintTemplateViewSet, basename="print-template")
router.register("roles", roles.RoleViewSet, basename="role")
router.register("users", roles.UserViewSet, basename="user")
router.register("attachments", attachments.AttachmentViewSet, basename="attachment")
router.register("file-categories", attachments.FileCategoryViewSet, basename="file-category")
router.register("counterparties", attachments.CounterpartyViewSet, basename="counterparty")

urlpatterns = [
    path("health/", views.health, name="core-health"),
    path("auth/csrf/", auth.csrf, name="core-csrf"),
    path("auth/login/", auth.login_view, name="core-login"),
    path("auth/logout/", auth.logout_view, name="core-logout"),
    path("me/", views.me, name="core-me"),
    path("me/pin/", views.set_my_pin, name="core-me-pin"),
    path("me/ui/", views.my_ui_settings, name="core-me-ui"),
    path("backup-status/", views.backup_status, name="core-backup-status"),
    *router.urls,
]
