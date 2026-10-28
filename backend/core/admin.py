from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.http import HttpResponse
from django.utils.html import format_html_join
from simple_history.admin import SimpleHistoryAdmin

from core import printing, services
from core.models import Clinic, PrintTemplate, User


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


class PrintTemplateForm(forms.ModelForm):  # type: ignore[type-arg]
    kind = forms.ChoiceField(label="Вид", choices=())

    class Meta:
        model = PrintTemplate
        fields = ("kind", "name", "is_active", "body")
        widgets = {
            "body": forms.Textarea(
                attrs={"rows": 30, "style": "width: 100%; font-family: monospace;"}
            )
        }

    def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = [(k.code, k.title) for k in printing.kinds()]


@admin.register(PrintTemplate)
class PrintTemplateAdmin(DirectoryAdmin):
    form = PrintTemplateForm
    list_display = ("name", "kind_title", "is_active")
    list_filter = ("kind", "is_active")
    readonly_fields = ("variables_help",)
    fields = ("kind", "name", "is_active", "body", "variables_help")
    actions = ("activate", "deactivate", "preview_pdf")

    @admin.display(description="Вид")
    def kind_title(self, template: PrintTemplate) -> str:
        try:
            return printing.get_kind(template.kind).title
        except printing.PrintTemplateError:
            return template.kind

    @admin.display(description="Доступные переменные и фильтры")
    def variables_help(self, template: PrintTemplate) -> str:
        variables = dict(printing.COMMON_VARIABLES)
        if template.kind:
            variables.update(printing.get_kind(template.kind).variables)
        rows = [(f"{{{{ {name} }}}}", text) for name, text in variables.items()]
        rows += [(f"|{name}", text) for name, text in printing.FILTERS_HELP.items()]
        return format_html_join("", "<div><code>{}</code> — {}</div>", rows)

    @admin.action(description="Предпросмотр PDF на примере данных")
    def preview_pdf(self, request, queryset):  # type: ignore[no-untyped-def]
        template = queryset.first()
        pdf = services.render_print_sample(template)
        return HttpResponse(pdf, content_type="application/pdf")
