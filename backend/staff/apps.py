from django.apps import AppConfig


class StaffConfig(AppConfig):
    name = "staff"
    verbose_name = "Сотрудники"

    def ready(self) -> None:
        from django.contrib.auth import get_user_model
        from django.db.models.signals import post_save

        from staff.models import Employee

        def create_profile(sender, instance, created, raw=False, **kwargs):  # type: ignore[no-untyped-def]
            # У каждой учётной записи есть профиль сотрудника — в том числе у созданных
            # через админку или createsuperuser.
            if created and not raw:
                Employee.objects.get_or_create(user=instance)

        post_save.connect(create_profile, sender=get_user_model(), dispatch_uid="staff_profile")
