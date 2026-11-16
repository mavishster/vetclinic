"""Новые разделы прав «Отчёты», «Выручка», «Профилактика»: выдать их тем, у кого был доступ.

Раньше страницы открывались по праву на счета/склад/профилактику. Чтобы после обновления
никто не потерял доступ, роли с прежним правом получают и новое; дальше руководитель
настраивает их отдельно.
"""

from django.contrib.auth.management import create_permissions
from django.db import migrations

# новое право → прежние права, по которым страница открывалась (любое из них)
GRANTS = {
    "view_reportsaccess": ["billing.view_invoice", "inventory.view_stockmovement"],
    "view_revenueaccess": ["billing.view_invoice"],
    "view_preventionreportaccess": ["medical.view_prevention"],
}


def grant(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    # Права создаются после миграций; новые права core нужны сразу. Прежние права других
    # приложений уже есть в базе, где есть роли с ними.
    core_config = apps.get_app_config("core")
    core_config.models_module = True
    create_permissions(core_config, apps=apps, verbosity=0)
    for new, old_codes in GRANTS.items():
        permission = Permission.objects.filter(
            content_type__app_label="core", codename=new
        ).first()
        if permission is None:
            continue
        for old in old_codes:
            app_label, codename = old.split(".")
            for group in Group.objects.filter(
                permissions__content_type__app_label=app_label,
                permissions__codename=codename,
            ).distinct():
                group.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0018_access_sections"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [migrations.RunPython(grant, migrations.RunPython.noop)]
