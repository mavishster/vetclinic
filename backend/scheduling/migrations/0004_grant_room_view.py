"""Справочник «Кабинеты»: просмотр — всем ролям, у которых есть просмотр записей на приём.

Окно «Пригласить в кабинет» показывает список кабинетов; чтобы после обновления врачам
и регистраторам не пришлось ждать настройки ролей, право выдаётся сразу. Дальше
руководитель настраивает его отдельно.
"""

from django.contrib.auth.management import create_permissions
from django.db import migrations


def grant(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    # Права создаются после миграций, а новое право нужно сразу.
    config = apps.get_app_config("scheduling")
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)
    permission = Permission.objects.filter(
        content_type__app_label="scheduling", codename="view_room"
    ).first()
    if permission is None:
        return
    for group in Group.objects.filter(
        permissions__content_type__app_label="scheduling",
        permissions__codename="view_appointment",
    ).distinct():
        group.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [
        ("scheduling", "0003_queue"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [migrations.RunPython(grant, migrations.RunPython.noop)]
