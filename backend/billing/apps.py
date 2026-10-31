from django.apps import AppConfig


class BillingConfig(AppConfig):
    name = "billing"
    verbose_name = "Счета"

    def ready(self) -> None:
        from billing import services
        from core.printing import register_kind

        register_kind(
            "invoice",
            "Счёт",
            variables={
                "invoice.number": "Номер",
                "invoice.date": "Дата (datetime)",
                "invoice.subtotal": "Сумма без скидки",
                "invoice.discount": "Скидка",
                "invoice.total": "К оплате",
                "invoice.status": "Статус",
                "client.full_name": "Клиент",
                "pet.name": "Питомец",
                "doctor.short_name": "Врач",
                "lines": "Строки: name, unit, quantity, price, discount, amount, composition "
                "(состав комбинации — по режиму печати: name, quantity, price, amount)",
            },
            sample=services.sample_print_context,
        )
