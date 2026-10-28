from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"
    verbose_name = "Ядро"

    def ready(self) -> None:
        from core.printing import register_kind

        # Общий вид: только общие переменные (клиника, сотрудник, дата).
        # Подходит для объявлений, памяток, бланков без данных документа.
        register_kind("general", "Общий документ")
