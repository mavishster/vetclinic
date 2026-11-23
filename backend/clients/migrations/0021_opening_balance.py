"""Остаток расчётов с клиентом на начало (перенос из прежней программы)."""

import core.fields
import django.db.models.deletion
import django.utils.timezone
import simple_history.models
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0020_pet_inactive_status'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='HistoricalOpeningBalance',
            fields=[
                ('id', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False)),
                ('created_at', models.DateTimeField(blank=True, editable=False, verbose_name='создано')),
                ('updated_at', models.DateTimeField(blank=True, editable=False, verbose_name='изменено')),
                ('version', models.PositiveIntegerField(default=1, editable=False, verbose_name='версия')),
                ('node_id', models.CharField(default='', editable=False, max_length=16, verbose_name='узел')),
                ('is_deleted', models.BooleanField(db_index=True, default=False, editable=False, verbose_name='удалено')),
                ('number', models.CharField(editable=False, max_length=32, verbose_name='номер')),
                ('date', models.DateTimeField(db_index=True, default=django.utils.timezone.now, verbose_name='дата')),
                ('status', models.CharField(choices=[('draft', 'черновик'), ('executed', 'выполнен')], default='draft', editable=False, max_length=16, verbose_name='статус')),
                ('executed_at', models.DateTimeField(blank=True, editable=False, null=True, verbose_name='выполнен')),
                ('comment', models.TextField(blank=True, verbose_name='комментарий')),
                ('amount', core.fields.MoneyField(decimal_places=2, max_digits=12, verbose_name='сумма (+ аванс клиента, − долг)')),
                ('history_id', models.AutoField(primary_key=True, serialize=False)),
                ('history_date', models.DateTimeField(db_index=True)),
                ('history_change_reason', models.CharField(max_length=100, null=True)),
                ('history_type', models.CharField(choices=[('+', 'Created'), ('~', 'Changed'), ('-', 'Deleted')], max_length=1)),
                ('client', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='clients.client', verbose_name='клиент')),
                ('created_by', models.ForeignKey(blank=True, db_constraint=False, editable=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='создал')),
                ('executed_by', models.ForeignKey(blank=True, db_constraint=False, editable=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='выполнил')),
                ('history_user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('updated_by', models.ForeignKey(blank=True, db_constraint=False, editable=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='изменил')),
            ],
            options={
                'verbose_name': 'historical остаток расчётов на начало',
                'verbose_name_plural': 'historical остатки расчётов на начало',
                'ordering': ('-history_date', '-history_id'),
                'get_latest_by': ('history_date', 'history_id'),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name='OpeningBalance',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='создано')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='изменено')),
                ('version', models.PositiveIntegerField(default=1, editable=False, verbose_name='версия')),
                ('node_id', models.CharField(default='', editable=False, max_length=16, verbose_name='узел')),
                ('is_deleted', models.BooleanField(db_index=True, default=False, editable=False, verbose_name='удалено')),
                ('number', models.CharField(editable=False, max_length=32, verbose_name='номер')),
                ('date', models.DateTimeField(db_index=True, default=django.utils.timezone.now, verbose_name='дата')),
                ('status', models.CharField(choices=[('draft', 'черновик'), ('executed', 'выполнен')], default='draft', editable=False, max_length=16, verbose_name='статус')),
                ('executed_at', models.DateTimeField(blank=True, editable=False, null=True, verbose_name='выполнен')),
                ('comment', models.TextField(blank=True, verbose_name='комментарий')),
                ('amount', core.fields.MoneyField(decimal_places=2, max_digits=12, verbose_name='сумма (+ аванс клиента, − долг)')),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='clients.client', verbose_name='клиент')),
                ('created_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='создал')),
                ('executed_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='выполнил')),
                ('updated_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='изменил')),
            ],
            options={
                'verbose_name': 'остаток расчётов на начало',
                'verbose_name_plural': 'остатки расчётов на начало',
                'ordering': ['-date'],
                'abstract': False,
                'constraints': [models.UniqueConstraint(fields=('number',), name='clients_openingbalance_unique_number')],
            },
        ),
    ]
