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
from medical.models import Diagnosis, Vaccination
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


def test_vaccination_closes_previous_reminder_and_books_repeat(pet, doctor, vaccine) -> None:
    first_visit = services.start_visit(pet, doctor)
    old = services.add_vaccination(
        first_visit, vaccine, next_date=timezone.localdate() + timedelta(days=21)
    )
    visit = services.start_visit(pet, doctor)
    next_year = timezone.localdate() + timedelta(days=365)

    new = services.add_vaccination(
        visit, vaccine, kind="secondary", next_date=next_year, repeat_at=time(10, 30)
    )

    old.refresh_from_db()
    assert old.reminder == Vaccination.Reminder.CLOSED
    assert new.reminder == Vaccination.Reminder.ACTIVE
    repeat = Appointment.objects.get(source="vaccination")
    assert timezone.localtime(repeat.start).date() == next_year
    assert repeat.purpose.kind == "vaccination"
    assert list(services.due_vaccinations(next_year)) == [new]


def test_vaccination_rules(pet, doctor, vaccine) -> None:
    visit = services.start_visit(pet, doctor)

    with pytest.raises(MedicalError, match="позже"):
        services.add_vaccination(visit, vaccine, next_date=timezone.localdate())
    with pytest.raises(MedicalError, match="больше нуля"):
        services.add_vaccination(visit, vaccine, quantity=D("0"))


def test_medcard_print(pet, doctor, vaccine) -> None:
    visit = services.start_visit(pet, doctor)
    visit.recommendations_html = "<p>Диета</p>"
    services.save_visit(visit)
    services.add_vaccination(visit, vaccine, batch_note="A123 до 12.2027")
    template = PrintTemplate.objects.get(kind="medcard")

    html = core.printing.render_html(
        template.body, {**core.common_print_context(), **services.print_context(visit)}
    )

    assert "Барсик" in html and "Нобивак Rabies" in html and "<p>Диета</p>" in html
    assert core.render_print(template, services.print_context(visit)).startswith(b"%PDF")
