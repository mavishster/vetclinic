from django.apps import AppConfig


class ClientsConfig(AppConfig):
    name = "clients"
    verbose_name = "Клиенты и питомцы"

    def ready(self) -> None:
        from core.attachments import register_owner

        # К клиентам и питомцам можно прикреплять файлы (договоры, сканы, снимки).
        register_owner("clients.client")
        register_owner("clients.pet")
