from django.apps import AppConfig


class MedicalConfig(AppConfig):
    name = "medical"
    verbose_name = "Медкарта"

    def ready(self) -> None:
        from core.attachments import register_owner
        from core.printing import register_kind
        from medical import services

        register_owner("medical.visit")  # снимки, результаты, сканы к записи медкарты
        register_kind(
            "medcard",
            "Медкарта (запись приёма)",
            variables={
                "pet.name": "Кличка", "pet.species": "Вид", "pet.breed": "Порода",
                "pet.sex": "Пол", "pet.birth_date": "Дата рождения (с фильтром date)",
                "pet.chip": "№ чипа", "client.full_name": "ФИО владельца",
                "doctor.full_name": "ФИО врача", "doctor.short_name": "Врач (Фамилия И. О.)",
                "visit.date": "Дата приёма (datetime)", "visit.purpose": "Цель обращения",
                "visit.result": "Результат", "visit.weight": "Вес, кг",
                "visit.temperature": "Температура", "visit.diagnoses": "Диагнозы",
                "visit.treatment": "Описание лечения (HTML — выводить с |safe)",
                "visit.recommendations": "Рекомендации (HTML — с |safe)",
                "visit.next_visit_date": "Дата повторного приёма",
                "vaccinations": "Список вакцинаций: vaccine, date, next_date, batch",
            },
            sample=services.sample_print_context,
        )  # fmt: skip
