from django.apps import AppConfig


class ClientsConfig(AppConfig):
    name = "clients"
    verbose_name = "Клиенты и питомцы"

    def ready(self) -> None:
        from clients import services
        from core.attachments import register_owner
        from core.printing import register_kind

        # К клиентам и питомцам можно прикреплять файлы (договоры, сканы, снимки).
        register_owner("clients.client")
        register_owner("clients.pet")
        register_kind(
            "client_document",
            "Документ клиента (на подпись)",
            variables={
                "client.full_name": "ФИО клиента", "client.phones": "Телефоны",
                "client.address": "Адрес", "client.email": "Email",
                "pets": "Питомцы: name, species, breed",
                "contract.number": "Номер договора", "contract.date": "Дата договора",
            },
            sample=services.sample_client_document_context,
        )  # fmt: skip
