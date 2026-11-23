"""Повторный перенос: отпечаток записи VetManager и версия нашей записи при переносе."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("vetmanager", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="imported",
            name="fingerprint",
            field=models.CharField(
                blank=True, max_length=64, verbose_name="отпечаток записи VetManager"
            ),
        ),
        migrations.AddField(
            model_name="imported",
            name="target_version",
            field=models.PositiveIntegerField(
                blank=True, null=True, verbose_name="версия нашей записи"
            ),
        ),
    ]
