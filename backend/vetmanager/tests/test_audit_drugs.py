"""Проверка препаратов: упаковка и розничная единица."""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from vetmanager import tidy
from vetmanager.management.commands.audit_drugs import audit

D = Decimal
pytestmark = pytest.mark.django_db


def unit(name: str) -> Unit:
    return Unit.objects.filter(name=name).first() or Unit.objects.create(name=name)


def drug(name: str, base: str, units: list[dict]) -> Item:
    return catalog.save_item(
        Item(
            kind=Kind.GOODS,
            name=name,
            group=ItemGroup.objects.filter(kind=Kind.GOODS).first(),
            base_unit=unit(base),
        ),
        [{"pricing": "fixed", "price": D("100"), "for_sale": True, **u} for u in units],
    )


def problems() -> dict[str, list[str]]:
    return {code: [i.name for i, _ in rows] for code, rows in audit().items()}


def test_correct_drug_has_no_remarks() -> None:
    drug(
        "Ношпа 8 табл.",
        "таб.",
        [
            {"unit": unit("таб.").pk, "ratio": D("1")},
            {"unit": unit("упак.").pk, "ratio": D("8"), "for_purchase": True},
        ],
    )

    assert not any(problems().values())


def test_pack_only_drug_has_no_retail_unit() -> None:
    drug("Цефтриаксон фл 10 мл", "фл.", [{"unit": unit("фл.").pk, "ratio": D("1")}])

    assert problems()["no_retail"] == ["Цефтриаксон фл 10 мл"]


def test_pack_in_name_but_not_in_record() -> None:
    drug("Ношпа 8 табл.", "таб.", [{"unit": unit("таб.").pk, "ratio": D("1")}])
    drug("Цефтриаксон 1 г", "г", [{"unit": unit("г").pk, "ratio": D("1")}])  # доза, не упаковка

    assert problems()["no_pack"] == ["Ношпа 8 табл."]


def test_pack_not_marked_for_purchase_and_pack_only_sale() -> None:
    drug(
        "Ношпа 8 табл.",
        "таб.",
        [
            {"unit": unit("таб.").pk, "ratio": D("1"), "for_sale": False},
            {"unit": unit("упак.").pk, "ratio": D("8")},
        ],
    )

    found = problems()
    assert found["no_purchase"] == ["Ношпа 8 табл."]
    assert found["cannot_sell"] == ["Ношпа 8 табл."]


def test_item_marked_ok_is_skipped() -> None:
    item = drug("Цефтриаксон фл 10 мл", "фл.", [{"unit": unit("фл.").pk, "ratio": D("1")}])
    tidy.skip_packaging(str(item.pk))

    assert not problems()["no_retail"]


def test_command_prints_summary_and_writes_csv(tmp_path) -> None:
    drug("Цефтриаксон фл 10 мл", "фл.", [{"unit": unit("фл.").pk, "ratio": D("1")}])
    out, path = StringIO(), tmp_path / "drugs.csv"

    call_command("audit_drugs", "--csv", str(path), stdout=out)

    assert "с замечаниями: 1" in out.getvalue()
    assert "Цефтриаксон фл 10 мл" in path.read_text(encoding="utf-8-sig")
