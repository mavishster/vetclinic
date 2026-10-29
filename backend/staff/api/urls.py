from rest_framework.routers import DefaultRouter

from staff.api import views

router = DefaultRouter()
router.register("positions", views.PositionViewSet, basename="position")
router.register("interval-types", views.IntervalTypeViewSet, basename="interval-type")
router.register("templates", views.IntervalTemplateViewSet, basename="interval-template")
router.register("employees", views.EmployeeViewSet, basename="employee")
router.register("intervals", views.IntervalViewSet, basename="interval")

urlpatterns = router.urls
