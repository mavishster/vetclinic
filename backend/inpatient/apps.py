from django.apps import AppConfig


class InpatientConfig(AppConfig):
    name = "inpatient"
    verbose_name = "Стационар"

    def ready(self) -> None:
        from core.printing import register_kind
        from inpatient import qr, services

        register_kind(
            "treatment_sheet",
            "Лист назначений (стационар)",
            variables={
                "pet.name": "Кличка", "pet.species": "Вид", "pet.breed": "Порода",
                "client.full_name": "Владелец", "doctor.full_name": "Лечащий врач",
                "ward": "Палата", "place": "Место", "day": "Дата листа",
                "day_number": "День в стационаре",
                "reason": "Причина госпитализации",
                "tasks": "Отметки: time, title, dose, route, status, done_by, note",
            },
            sample=services.sample_sheet_context,
        )  # fmt: skip
        register_kind(
            "hospitalization_qr",
            "QR-этикетка пациента (стационар)",
            variables={
                "sheets": "Листы А4: список листов, в каждом — этикетки",
                "labels": "Все этикетки подряд",
                "label.fields": "Поля этикетки: code, label, value (выбор — в настройках клиники)",
                "label.qr": "QR-код картинкой: <img src=\"{{ label.qr }}\">",
                "label.url": "Ссылка, зашитая в код",
                "size.qr": "Размер QR-кода, мм",
                "size.label_w": "Ширина этикетки, мм",
                "size.label_h": "Высота этикетки, мм",
                "size.cols": "Этикеток в ряду на листе",
                "size.rows": "Рядов на листе",
            },
            sample=qr.sample_context,
        )  # fmt: skip
