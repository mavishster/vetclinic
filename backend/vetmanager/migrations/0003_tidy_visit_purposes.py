"""Цели обращения: убрать то, что попало из чужих разделов справочника VetManager.

Перенос брал из общего справочника VetManager (ComboManualItem) и элементы без раздела —
так в цели обращения попали типы кассовых операций («Инкассация», «Оплата поставщику»),
источники клиентов, производители. Импорт исправлен; здесь убирается уже перенесённое.

Удаляется (мягко) цель, только если всё сразу:
- она пришла из VetManager;
- на неё не ссылается ни одна медкарта, запись на приём или шаблон медкарты;
- её нет в начальном списке целей (scheduling, 0002) — «Звонок» или «УЗИ» остаются.
Настоящие типы приёма VetManager использовались в медкартах — они не трогаются.
Цели, которые клиника завела сама, тоже не трогаются.
"""

from django.db import migrations

INITIAL = {
    "первичный", "повторный", "вакцинация", "взятие анализа", "экстренный", "хирургия",
    "рентген", "узи", "груминг", "стационар", "эвтаназия", "звонок", "задача",
}  # fmt: skip


def junk_purposes(apps):  # type: ignore[no-untyped-def]
    """Цели, которые нужно убрать (запрос; ничего не меняет)."""
    VisitPurpose = apps.get_model("scheduling", "VisitPurpose")
    Appointment = apps.get_model("scheduling", "Appointment")
    Visit = apps.get_model("medical", "Visit")
    TextTemplate = apps.get_model("medical", "TextTemplate")
    Imported = apps.get_model("vetmanager", "Imported")

    imported = Imported.objects.filter(kind="visit_purpose").values("target_id")
    used = set()
    for model in (Visit, Appointment, TextTemplate):
        # Менеджер миграций видит и мягко удалённые записи — они тоже держат цель.
        used |= set(model.objects.exclude(purpose=None).values_list("purpose_id", flat=True))
    return [
        purpose
        for purpose in VisitPurpose.objects.filter(is_deleted=False, pk__in=imported)
        if purpose.pk not in used and purpose.name.strip().lower() not in INITIAL
    ]


def tidy(apps, schema_editor):  # type: ignore[no-untyped-def]
    VisitPurpose = apps.get_model("scheduling", "VisitPurpose")
    junk = [purpose.pk for purpose in junk_purposes(apps)]
    VisitPurpose.objects.filter(pk__in=junk).update(is_deleted=True, is_active=False)


class Migration(migrations.Migration):
    dependencies = [
        ("vetmanager", "0002_imported_sync"),
        ("scheduling", "0004_grant_room_view"),
        ("medical", "0013_alter_prescription_options_and_more"),
    ]
    operations = [migrations.RunPython(tidy, migrations.RunPython.noop)]
