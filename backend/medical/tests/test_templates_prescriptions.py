"""Текстовые шаблоны (переменные, поля), назначения, памятка владельцу, позиции в счёт."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from clients import services as clients
from clients.models import Breed, Client, Pet, Species
from core import services as core
from core.models import PrintTemplate
from medical import services
from medical.models import TextTemplate
from medical.services import MedicalError

D = Decimal


@pytest.fixture
def doctor(db):
    return get_user_model().objects.create_user(
        username="doc", password="x", last_name="Иванова", first_name="Анна"
    )


@pytest.fixture
def visit(doctor):
    owner = clients.save_client(Client(last_name="Петров", first_name="Пётр"))
    cats = Species.objects.get(name="Кошки")
    born = timezone.localdate() - timedelta(days=3 * 365 + 70)
    pet = clients.save_pet(
        Pet(
            owner=owner,
            name="Барсик",
            species=cats,
            breed=Breed.objects.get(name="Метис", species=cats),
            birth_date=born,
        )
    )
    v = services.start_visit(pet, doctor)
    v.weight, v.temperature = D("4.25"), D("38.6")
    return services.save_visit(v)


@pytest.fixture
def milbemax(db):
    return catalog.save_item(
        Item(
            kind=Kind.GOODS,
            name="Мильбемакс",
            group=ItemGroup.objects.get(name="Препараты"),
            base_unit=Unit.objects.get(name="таб."),
        ),
        [{"unit": Unit.objects.get(name="таб."), "price": D("350")}],
    )


def test_render_substitutes_variables_and_marks_fields(visit) -> None:
    template = services.save_template(
        TextTemplate(
            name="Т",
            body_html="<p>{Кличка}, {возраст}, {вес} кг, {неизвестно}. Жалобы: [___ со слов]. Стул [___].</p><script>x</script>",
        )
    )

    html = services.render_template(template, visit)

    assert "Барсик, 3 года 2 мес., 4,25 кг, {неизвестно}" in html
    assert '<span class="fill-field">со слов</span>' in html
    assert '<span class="fill-field">___</span>' in html
    assert "script" not in template.body_html


def test_empty_variable_becomes_field(visit) -> None:
    visit.temperature = None
    template = services.save_template(
        TextTemplate(name="Т2", body_html="<p>t {температура} °C</p>")
    )

    assert (
        services.render_template(template, visit)
        == '<p>t <span class="fill-field">температура</span> °C</p>'
    )


def test_age_text_variants(visit) -> None:
    pet = visit.pet
    pet.birth_date = timezone.localdate() - timedelta(days=40)
    assert services.age_text(pet) == "1 мес."
    pet.birth_date_approximate = True
    pet.birth_date = date(2020, 1, 1)
    assert services.age_text(pet, date(2022, 1, 1)) == "≈ 2 года"


def test_templates_for_section_purpose_and_personal(visit, doctor) -> None:
    other = get_user_model().objects.create_user(username="doc2", password="x")
    vaccination = visit.purpose.__class__.objects.get(kind="vaccination")
    services.save_template(
        TextTemplate(name="Мой осмотр", section="treatment", owner=doctor, body_html="x")
    )
    services.save_template(
        TextTemplate(name="Чужой", section="treatment", owner=other, body_html="x")
    )

    names = [t.name for t in services.templates_for(doctor, "treatment", vaccination.pk)]

    assert names[0] == "Вакцинация — осмотр"  # для цели приёма — первым
    assert "Мой осмотр" in names and "Чужой" not in names
    assert "Гастроэнтерит — рекомендации" not in names  # другая вкладка


def test_prescriptions_saved_and_sold_into_invoice(visit, milbemax) -> None:
    tablet = milbemax.units.get()
    services.save_prescriptions(visit, [
        {"item": milbemax, "dose": "1 таб.", "route": "oral", "frequency": "однократно", "sell_unit": tablet, "sell_qty": D("2")},
        {"drug_name": "Хлоргексидин 0,05%", "route": "topical", "frequency": "2 раза в день", "days": 5},
    ])  # fmt: skip

    lines = services.invoice_lines(visit)

    assert [p.drug_name for p in visit.prescriptions.all()] == ["Мильбемакс", "Хлоргексидин 0,05%"]
    assert lines == [{"item_unit": tablet.pk, "quantity": D("2.000"), "performer": visit.doctor_id}]


def test_prescription_rules(visit, milbemax) -> None:
    with pytest.raises(MedicalError, match="не указан препарат"):
        services.save_prescriptions(visit, [{"dose": "1"}])
    with pytest.raises(MedicalError, match="сколько продать"):
        services.save_prescriptions(visit, [{"item": milbemax, "sell_unit": milbemax.units.get()}])


def test_prescriptions_print(visit, milbemax) -> None:
    services.save_prescriptions(
        visit, [{"item": milbemax, "dose": "1 таб.", "frequency": "однократно"}]
    )
    template = PrintTemplate.objects.get(kind="prescriptions")

    assert core.render_print(template, services.prescriptions_context(visit)).startswith(b"%PDF")


def test_api_templates_render_and_prescriptions(visit, milbemax) -> None:
    api = APIClient()
    api.force_authenticate(get_user_model().objects.create_superuser(username="a", password="x"))
    created = api.post(
        "/api/medical/text-templates/",
        {
            "name": "Личный",
            "section": "recommendations",
            "body_html": "<p>{кличка}: [___]</p>",
            "personal": True,
        },
        format="json",
    ).json()

    picked = api.get("/api/medical/text-templates/?section=recommendations").json()
    rendered = api.post(
        f"/api/medical/visits/{visit.pk}/render-template/",
        {"template": created["id"]},
        format="json",
    ).json()
    saved = api.put(
        f"/api/medical/visits/{visit.pk}/prescriptions/",
        {"rows": [{"item": str(milbemax.pk), "dose": "1 таб."}]},
        format="json",
    )
    variables = api.get("/api/medical/text-templates/variables/").json()
    pdf = api.get(f"/api/medical/visits/{visit.pk}/print-prescriptions/")

    assert created["is_personal"] is True
    assert picked[0]["name"] == "Личный"  # личные — первыми
    assert rendered["html"] == '<p>Барсик: <span class="fill-field">___</span></p>'
    assert saved.json()["prescriptions"][0]["drug_name"] == "Мильбемакс"
    assert "{кличка}" in [v["name"] for v in variables]
    assert pdf["Content-Type"] == "application/pdf"
