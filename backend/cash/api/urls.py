from django.urls import path
from rest_framework.routers import DefaultRouter

from cash.api import views

router = DefaultRouter()
router.register("registers", views.CashRegisterViewSet, basename="cash-register")
router.register("payments", views.PaymentViewSet, basename="payment")
router.register("operations", views.CashOperationViewSet, basename="cash-operation")
router.register("cash", views.CashViewSet, basename="cash")

urlpatterns = [
    path("reports/money/", views.MoneyReportView.as_view(), name="report-money"),
    *router.urls,
]
