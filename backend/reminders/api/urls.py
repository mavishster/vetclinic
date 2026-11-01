from rest_framework.routers import DefaultRouter

from reminders.api import views

router = DefaultRouter()
router.register("reminders", views.ReminderViewSet, basename="reminder")

urlpatterns = router.urls
