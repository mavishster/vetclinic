from django.apps import AppConfig


class InventoryConfig(AppConfig):
    name = "inventory"
    verbose_name = "Склад"

    def ready(self) -> None:
        from core.printing import register_kind
        from inventory import labels

        register_kind(
            "label",
            "Этикетка товара",
            variables={
                "labels": "Список этикеток (по одной на копию): name, unit, price, barcode, "
                "barcode_svg (картинка штрихкода — выводить с |safe), series, expiry_date, article",
            },
            sample=labels.sample_context,
        )
