"""Ввод остатков по списку из старого файла склада."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0013_department_warehouses'),
    ]

    operations = [
        migrations.AddField(
            model_name='historicalstockdocument',
            name='checklist',
            field=models.JSONField(blank=True, default=list, verbose_name='список из файла'),
        ),
        migrations.AddField(
            model_name='historicalstockdocument',
            name='checklist_name',
            field=models.CharField(blank=True, max_length=200, verbose_name='файл списка'),
        ),
        migrations.AddField(
            model_name='stockdocument',
            name='checklist',
            field=models.JSONField(blank=True, default=list, verbose_name='список из файла'),
        ),
        migrations.AddField(
            model_name='stockdocument',
            name='checklist_name',
            field=models.CharField(blank=True, max_length=200, verbose_name='файл списка'),
        ),
        migrations.AddField(
            model_name='stockline',
            name='checklist_row',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='строка файла'),
        ),
    ]
