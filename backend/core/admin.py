from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from simple_history.admin import SimpleHistoryAdmin

from core import services
from core.models import Clinic, User


@admin.register(User)
class UserAdmin(SimpleHistoryAdmin, DjangoUserAdmin):
    list_display = ("username", "last_name", "first_name", "middle_name", "is_active", "has_pin")
    readonly_fields = ("has_pin",)
    actions = ("reset_pin",)
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("ФИО и контакты", {"fields": ("last_name", "first_name", "middle_name", "email")}),
        ("ПИН для подтверждения операций", {"fields": ("has_pin",)}),
        (
            "Права",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Даты", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "last_name",
                    "first_name",
                    "middle_name",
                    "usable_password",
                    "password1",
                    "password2",
                ),
            },
        ),
    )

    @admin.display(description="ПИН задан", boolean=True)
    def has_pin(self, user: User) -> bool:
        return user.has_pin

    @admin.action(description="Сбросить ПИН выбранным")
    def reset_pin(self, request, queryset):  # type: ignore[no-untyped-def]
        for user in queryset:
            services.reset_pin(user)


@admin.register(Clinic)
class ClinicAdmin(SimpleHistoryAdmin):  # type: ignore[misc]
    list_display = ("name", "address", "phone")


class DirectoryAdmin(SimpleHistoryAdmin):  # type: ignore[misc]
    """Общая админка справочников (DRY): поиск, фильтр, действия активации."""

    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    actions = ("activate", "deactivate")

    @admin.action(description="Активировать выбранные")
    def activate(self, request, queryset):  # type: ignore[no-untyped-def]
        self._set_active(queryset, active=True)

    @admin.action(description="Деактивировать выбранные")
    def deactivate(self, request, queryset):  # type: ignore[no-untyped-def]
        self._set_active(queryset, active=False)

    @staticmethod
    def _set_active(queryset, active: bool) -> None:  # type: ignore[no-untyped-def]
        # Через save(), а не update(): растёт версия и пишется «кто изменил» (ADR-002).
        for entry in queryset:
            entry.is_active = active
            entry.save(update_fields=["is_active"])
