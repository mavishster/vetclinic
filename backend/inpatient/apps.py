from django.apps import AppConfig


class InpatientConfig(AppConfig):
    name = "inpatient"
    verbose_name = "Стационар"

    def ready(self) -> None:
        from core.printing import register_kind
        from inpatient import services

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
