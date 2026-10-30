"""Медкарта: начало приёма, сохранение, позиции из «@», вес, вакцинации, печать."""

from datetime import time, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from clients import services as clients
from clients.models import Breed, Client, Pet, Species
from core import services as core
from core.models import PrintTemplate
from medical import services
from medical.models import Diagnosis, Prevention, PreventionType
from medical.services import MedicalError
from scheduling import services as scheduling
from scheduling.models import Appointment

D = Decimal


@pytest.fixture
def doctor(db):
    return get_user_model().objects.create_user(
        username="doc", password="x", last_name="Иванова", first_name="Анна"
    )


@pytest.fixture
def pet(db):
    owner = clients.save_client(Client(last_name="Петров"))
    cats = Species.objects.get(name="Кошки")
    pet = clients.save_pet(
        Pet(
            owner=owner,
            name="Барсик",
            species=cats,
            breed=Breed.objects.get(name="Метис", species=cats),
        )
    )
    clients.add_weight(pet, D("4.1"), timezone.localdate() - timedelta(days=30))
    return pet


@pytest.fixture
def vaccine(db):
    return catalog.save_item(
        Item(
            kind=Kind.GOODS,
            name="Нобивак Rabies",
            group=ItemGroup.objects.get(name="Вакцины"),
            base_unit=Unit.objects.get(name="доза"),
        ),
        [{"unit": Unit.objects.get(name="доза"), "price": D("700")}],
    )


def test_start_visit_takes_owner_last_weight_and_default_purpose(pet, doctor) -> None:
    visit = services.start_visit(pet, doctor)

    assert visit.client == pet.owner
    assert visit.weight == D("4.100")
    assert visit.purpose.name == "Первичный"  # первая из обычных целей, а не по алфавиту


def test_visit_from_appointment_marks_in_progress_and_reuses_visit(pet, doctor) -> None:
    appointment = scheduling.save_appointment(
        Appointment(client=pet.owner, pet=pet, doctor=doctor, purpose=scheduling.purpose_of_kind("vaccination"),
                    start=timezone.now(), end=timezone.now() + timedelta(minutes=20)),
        force=True,
    )  # fmt: skip

    visit = services.visit_for_appointment(appointment, doctor)
    again = services.visit_for_appointment(appointment, doctor)
    services.complete_visit(visit)

    appointment.refresh_from_db()
    assert visit.purpose.kind == "vaccination"
    assert again.pk == visit.pk
    assert appointment.status == "completed"


def test_appointment_without_pet_card_is_explained(doctor) -> None:
    client = clients.save_client(Client(last_name="Смирнова", status="temporary"))
    appointment = scheduling.save_appointment(
        Appointment(
            client=client,
            pet_note="кошка",
            start=timezone.now(),
            end=timezone.now() + timedelta(minutes=20),
        ),
        force=True,
    )

    with pytest.raises(MedicalError, match="заведите питомца"):
        services.visit_for_appointment(appointment, doctor)


def test_save_cleans_html_collects_mentions_and_records_weight(pet, doctor, vaccine) -> None:
    unit_id = vaccine.units.get().pk
    visit = services.start_visit(pet, doctor)
    mention = f'<span class="item-mention" data-item-unit="{unit_id}" contenteditable="false">Нобивак</span>'
    visit.treatment_html = f"<p onclick='x'>Осмотр {mention} {mention}<script>alert(1)</script></p>"
    visit.recommendations_html = f"<p>Повтор через год {mention}</p>"
    visit.weight = D("4.35")

    services.save_visit(visit, [(Diagnosis.objects.get(name="Клинически здоров"), "final")])

    assert "script" not in visit.treatment_html and "onclick" not in visit.treatment_html
    assert {(i.section, i.quantity) for i in visit.items.all()} == {
        ("treatment", D("2")),
        ("recommendations", D("1")),
    }
    assert visit.diagnoses.get().kind == "final"
    assert clients.current_weight(pet).weight == D("4.350")
    services.save_visit(visit)  # повторное сохранение не плодит взвешивания
    assert pet.weights.filter(date=timezone.localdate()).count() == 1


def test_temperature_and_weight_checks(pet, doctor) -> None:
    visit = services.start_visit(pet, doctor)
    visit.temperature = D("55")

    with pytest.raises(MedicalError, match="температуру"):
        services.save_visit(visit)


def ptype(kind: str) -> PreventionType:
    return PreventionType.objects.get(kind=kind)


def test_vaccination_closes_previous_reminder_of_same_vaccine_and_books_repeat(
    pet, doctor, vaccine
) -> None:
    first_visit = services.start_visit(pet, doctor)
    old = services.add_prevention(
        first_visit,
        ptype("vaccination"),
        vaccine,
        next_date=timezone.localdate() + timedelta(days=21),
    )
    visit = services.start_visit(pet, doctor)
    next_year = timezone.localdate() + timedelta(days=365)

    new = services.add_prevention(
        visit,
        ptype("vaccination"),
        vaccine,
        stage="secondary",
        next_date=next_year,
        repeat_at=time(10, 30),
    )

    old.refresh_from_db()
    assert old.reminder == Prevention.Reminder.CLOSED
    assert new.reminder == Prevention.Reminder.ACTIVE
    repeat = Appointment.objects.get(source="vaccination")
    assert timezone.localtime(repeat.start).date() == next_year
    assert repeat.purpose.kind == "vaccination"
    assert list(services.due_preventions(next_year)) == [new]


def test_repeat_date_defaults_from_type_and_deworming_closes_any_product(pet, doctor) -> None:
    milbemax = catalog.save_item(
        Item(
            kind=Kind.GOODS,
            name="Мильбемакс",
            group=ItemGroup.objects.get(name="Препараты"),
            base_unit=Unit.objects.get(name="таб."),
            prevention_kind="deworming",
        ),
        [{"unit": Unit.objects.get(name="таб."), "price": D("350")}],
    )
    visit = services.start_visit(pet, doctor)
    first = services.add_prevention(visit, ptype("deworming"), milbemax)
    other = catalog.save_item(
        Item(
            kind=Kind.GOODS,
            name="Празицид",
            group=ItemGroup.objects.get(name="Препараты"),
            base_unit=Unit.objects.get(name="таб."),
            prevention_kind="deworming",
        ),
        [{"unit": Unit.objects.get(name="таб."), "price": D("200")}],
    )
    second = services.add_prevention(services.start_visit(pet, doctor), ptype("deworming"), other)

    first.refresh_from_db()
    assert first.next_date == timezone.localdate() + timedelta(days=90)
    assert first.reminder == Prevention.Reminder.CLOSED
    assert second.reminder == Prevention.Reminder.ACTIVE
    assert [i.name for i in services.preparations(ptype("deworming"))] == ["Мильбемакс", "Празицид"]


def test_sterilization_and_chipping_update_pet_card(pet, doctor) -> None:
    visit = services.start_visit(pet, doctor)

    sterilization = services.add_prevention(
        visit, ptype("sterilization"), next_date=timezone.localdate() + timedelta(days=5)
    )
    with pytest.raises(MedicalError, match="номер чипа"):
        services.add_prevention(visit, ptype("chipping"))
    services.add_prevention(visit, ptype("chipping"), note=" 643094100999888 ")

    pet.refresh_from_db()
    assert pet.sterilized
    assert pet.chip_number == "643094100999888"
    assert sterilization.next_date is None  # однократная — без повтора
    assert sterilization.reminder == Prevention.Reminder.CLOSED


def test_prevention_rules(pet, doctor, vaccine) -> None:
    visit = services.start_visit(pet, doctor)

    with pytest.raises(MedicalError, match="позже"):
        services.add_prevention(
            visit, ptype("vaccination"), vaccine, next_date=timezone.localdate()
        )
    with pytest.raises(MedicalError, match="больше нуля"):
        services.add_prevention(visit, ptype("vaccination"), vaccine, quantity=D("0"))
    with pytest.raises(MedicalError, match="вакцину"):
        services.add_prevention(visit, ptype("vaccination"))


def test_summary_shows_last_per_vaccine_and_overdue(pet, doctor, vaccine) -> None:
    visit = services.start_visit(pet, doctor)
    services.add_prevention(
        visit, ptype("vaccination"), vaccine, next_date=timezone.localdate() + timedelta(days=30)
    )
    Prevention.objects.update(next_date=timezone.localdate() - timedelta(days=1))  # срок прошёл

    summary = {row["type"]: row for row in services.prevention_summary(pet)}

    assert summary["Вакцинация"]["last"]["item"] == "Нобивак Rabies"
    assert summary["Вакцинация"]["overdue"] is True
    assert summary["Стерилизация / кастрация"]["last"] is None  # «не проводилась»


def test_report_done_due_overdue(pet, doctor, vaccine) -> None:
    today = timezone.localdate()
    visit = services.start_visit(pet, doctor)
    services.add_prevention(
        visit, ptype("vaccination"), vaccine, next_date=today + timedelta(days=10)
    )

    done = services.prevention_report("done", today, today)
    due = services.prevention_report(
        "due", today, today + timedelta(days=30), type_id=ptype("vaccination").pk
    )
    overdue = services.prevention_report("overdue", today, today)

    assert done.count() == 1 and due.count() == 1 and overdue.count() == 0
    with pytest.raises(MedicalError):
        services.prevention_report("всё", today, today)


def test_suggestions_from_mentioned_items(pet, doctor, vaccine) -> None:
    castration = catalog.save_item(
        Item(
            kind=Kind.SERVICE,
            name="Кастрация кота",
            group=ItemGroup.objects.get(name="Хирургия"),
            base_unit=Unit.objects.get(name="усл."),
            prevention_kind="sterilization",
        ),
        [{"unit": Unit.objects.get(name="усл."), "price": D("3500")}],
    )
    visit = services.start_visit(pet, doctor)
    mention = '<span class="item-mention" data-item-unit="{}">x</span>'
    visit.treatment_html = mention.format(castration.units.get().pk) + mention.format(
        vaccine.units.get().pk
    )
    services.save_visit(visit)

    names = {s["type_name"] for s in services.prevention_suggestions(visit)}
    assert names == {"Стерилизация / кастрация", "Вакцинация"}

    services.add_prevention(visit, ptype("vaccination"), vaccine)
    assert {s["type_name"] for s in services.prevention_suggestions(visit)} == {
        "Стерилизация / кастрация"
    }


def test_medcard_print(pet, doctor, vaccine) -> None:
    visit = services.start_visit(pet, doctor)
    visit.recommendations_html = "<p>Диета</p>"
    services.save_visit(visit)
    services.add_prevention(visit, ptype("vaccination"), vaccine, batch_note="A123 до 12.2027")
    template = PrintTemplate.objects.get(kind="medcard")

    html = core.printing.render_html(
        template.body, {**core.common_print_context(), **services.print_context(visit)}
    )

    assert "Барсик" in html and "Нобивак Rabies" in html and "<p>Диета</p>" in html
    assert core.render_print(template, services.print_context(visit)).startswith(b"%PDF")


def test_preparation_required_for_deworming_but_not_for_sterilization(pet, doctor) -> None:
    visit = services.start_visit(pet, doctor)

    with pytest.raises(
        MedicalError, match="Выберите препарат — для «Дегельминтизация» он обязателен"
    ):
        services.add_prevention(visit, ptype("deworming"))
    assert services.add_prevention(visit, ptype("sterilization")).pk


def test_update_prevention(pet, doctor, vaccine) -> None:
    visit = services.start_visit(pet, doctor)
    record = services.add_prevention(visit, ptype("vaccination"), vaccine)
    later = timezone.localdate() + timedelta(days=200)

    services.update_prevention(record, next_date=later, batch_note="B777", quantity=D("2"))
    record.refresh_from_db()
    assert (record.next_date, record.batch_note, record.quantity) == (later, "B777", D("2.000"))

    with pytest.raises(MedicalError, match="вакцину"):
        services.update_prevention(record, item=None)
    with pytest.raises(MedicalError, match="не меняются"):
        services.update_prevention(record, type=ptype("deworming"))


def test_chip_number_correction_updates_pet(pet, doctor) -> None:
    visit = services.start_visit(pet, doctor)
    record = services.add_prevention(visit, ptype("chipping"), note="111")

    services.update_prevention(record, note="643094100555444")

    pet.refresh_from_db()
    assert pet.chip_number == "643094100555444"


def test_doctor_can_be_changed_to_active_employee_only(pet, doctor) -> None:
    visit = services.start_visit(pet, doctor)
    other = get_user_model().objects.create_user(
        username="doc2", password="x", last_name="Сидорова"
    )

    visit.doctor = other
    services.save_visit(visit)
    assert visit.doctor == other

    other.is_active = False
    other.save()
    with pytest.raises(MedicalError, match="уволен"):
        services.save_visit(visit)
    assert doctor in services.doctors() and other not in services.doctors()


def test_delete_visit_removes_its_preventions_from_reports(pet, doctor, vaccine) -> None:
    visit = services.start_visit(pet, doctor)
    services.add_prevention(visit, ptype("vaccination"), vaccine)
    today = timezone.localdate()

    services.delete_visit(visit)

    assert not services.pet_visits(pet).filter(pk=visit.pk).exists()
    assert services.prevention_report("done", today, today).count() == 0
    assert services.due_preventions(today + timedelta(days=400)).count() == 0


def test_batch_fills_series_and_expiry(pet, doctor, vaccine) -> None:
    from datetime import date

    from core import services as core_services
    from inventory import services as inventory
    from inventory.models import StockDocument, Warehouse

    receipt = inventory.save_document(
        StockDocument(kind="receipt", warehouse=Warehouse.objects.get(name="Основной склад")),
        [
            {
                "item_unit": vaccine.units.get(),
                "quantity": D("5"),
                "price": D("400"),
                "series": "NB-77",
                "expiry_date": date(2027, 12, 31),
            }
        ],
    )
    core_services.execute_document(receipt)
    batch = services.batches_for(vaccine)[0].batch
    visit = services.start_visit(pet, doctor)

    record = services.add_prevention(visit, ptype("vaccination"), vaccine, batch=batch)

    assert record.batch_note == "NB-77, годен до 31.12.2027"
    other = catalog.save_item(
        Item(
            kind=Kind.GOODS,
            name="Другая вакцина",
            group=ItemGroup.objects.get(name="Вакцины"),
            base_unit=Unit.objects.get(name="доза"),
        ),
        [{"unit": Unit.objects.get(name="доза"), "price": D("500")}],
    )
    with pytest.raises(MedicalError, match="другому препарату"):
        services.add_prevention(visit, ptype("vaccination"), other, batch=batch)
