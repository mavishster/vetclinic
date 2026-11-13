"""Сквозной номер клиента: поле, затем номера для уже заведённых клиентов."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("clients", "0017_default_client_type")]

    operations = [
        migrations.AddField(
            model_name="client",
            name="number",
            field=models.PositiveIntegerField(
                editable=False, null=True, unique=True, verbose_name="№ клиента"
            ),
        ),
        migrations.AddField(
            model_name="historicalclient",
            name="number",
            field=models.PositiveIntegerField(
                db_index=True, editable=False, null=True, verbose_name="№ клиента"
            ),
        ),
    ]
