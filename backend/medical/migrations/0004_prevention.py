"""Вакцинации → общая профилактика: виды профилактики, препарат или услуга, этап, примечание.

Существующие вакцинации сохраняются и получают вид «Вакцинация».
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

TYPES = [
    # название, поведение, повтор через дней (None — однократно)
    ("Вакцинация", "vaccination", 365),
    ("Дегельминтизация", "deworming", 90),
    ("Обработка от эктопаразитов", "ectoparasites", 30),
    ("Стерилизация / кастрация", "sterilization", None),
    ("Чипирование", "chipping", None),
]


def create_types(apps, schema_editor):
    PreventionType = apps.get_model("medical", "PreventionType")
    Prevention = apps.get_model("medical", "Prevention")
    for name, kind, days in TYPES:
        PreventionType.objects.get_or_create(
            name=name, defaults={"node_id": settings.NODE_ID, "kind": kind, "repeat_days": days}
        )
    vaccination = PreventionType.objects.get(kind="vaccination")
    Prevention.objects.filter(type__isnull=True).update(type=vaccination)


class Migration(migrations.Migration):
    dependencies = [
        ("medical", "0003_medcard_print_template"),
        ("catalog", "0004_prevention_kind"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PreventionType",
            fields=[
                ("id", models.UUIDField(editable=False, primary_key=True, serialize=False, default=__import__("uuid").uuid4)),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="изменено")),
                ("version", models.PositiveIntegerField(default=1, editable=False, verbose_name="версия")),
                ("node_id", models.CharField(default="", editable=False, max_length=16, verbose_name="узел")),
                ("is_deleted", models.BooleanField(db_index=True, default=False, editable=False, verbose_name="удалено")),
                ("name", models.CharField(max_length=200, verbose_name="название")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="активна")),
                ("kind", models.CharField(choices=[("vaccination", "вакцинация"), ("deworming", "дегельминтизация"), ("ectoparasites", "обработка от эктопаразитов"), ("sterilization", "стерилизация / кастрация"), ("chipping", "чипирование"), ("other", "другое")], default="other", max_length=16, verbose_name="поведение")),
                ("repeat_days", models.PositiveIntegerField(blank=True, help_text="Пусто — процедура однократная", null=True, verbose_name="повтор через, дней")),
                ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="создал")),
                ("updated_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="изменил")),
            ],
            options={"verbose_name": "вид профилактики", "verbose_name_plural": "виды профилактики", "ordering": ["name"], "abstract": False},
        ),
        migrations.AddConstraint(
            model_name="preventiontype",
            constraint=models.UniqueConstraint(models.functions.Lower("name"), condition=models.Q(("is_deleted", False)), name="medical_preventiontype_unique_name"),
        ),
        migrations.RenameModel("Vaccination", "Prevention"),
        migrations.RenameModel("HistoricalVaccination", "HistoricalPrevention"),
        migrations.RenameField("prevention", "vaccine", "item"),
        migrations.RenameField("historicalprevention", "vaccine", "item"),
        migrations.RenameField("prevention", "kind", "stage"),
        migrations.RenameField("historicalprevention", "kind", "stage"),
        migrations.AddField(
            model_name="prevention", name="type",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, to="medical.preventiontype", verbose_name="вид"),
        ),
        migrations.AddField(
            model_name="historicalprevention", name="type",
            field=models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name="+", to="medical.preventiontype", verbose_name="вид"),
        ),
        migrations.RunPython(create_types, migrations.RunPython.noop),
    ]
