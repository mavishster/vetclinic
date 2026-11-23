"""Счёт, перенесённый из VetManager: при выполнении склад не трогается."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0009_alter_invoiceline_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='historicalinvoice',
            name='imported',
            field=models.BooleanField(default=False, editable=False, verbose_name='перенесён из VetManager'),
        ),
        migrations.AddField(
            model_name='invoice',
            name='imported',
            field=models.BooleanField(default=False, editable=False, verbose_name='перенесён из VetManager'),
        ),
    ]
