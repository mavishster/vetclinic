"""Этикетки со штрихкодами: на товар (единицу) или на партию из прихода."""

import io
from typing import Any, TypedDict

import barcode
from barcode.writer import SVGWriter

from catalog import services as catalog
from core import services as core


class LabelRequest(TypedDict, total=False):
    item_unit: Any
    copies: int
    batch: Any


def barcode_svg(code: str) -> str:
    """SVG штрихкода: EAN-13 для 13 цифр, иначе Code 128."""
    kind = "ean13" if code.isdigit() and len(code) == 13 else "code128"
    value = code[:12] if kind == "ean13" else code
    out = io.BytesIO()
    barcode.get(kind, value, writer=SVGWriter()).write(
        out,
        options={
            "module_height": 9,
            "module_width": 0.25,
            "font_size": 5,
            "text_distance": 2.5,
            "quiet_zone": 1.5,
        },
    )
    svg = out.getvalue().decode()
    return svg[svg.index("<svg") :]  # без XML-заголовка — для вставки в HTML


MAX_LABELS = 1000


def label_context(requests: list[LabelRequest]) -> dict[str, Any]:
    """Данные печатной формы «Этикетка»: по строке на каждую копию."""
    from inventory.models import Batch  # своя модель модуля

    labels: list[dict[str, Any]] = []
    for request in requests:
        unit = catalog.get_item_unit(
            getattr(request.get("item_unit"), "pk", request.get("item_unit"))
        )
        if unit is None:
            continue
        code = catalog.ensure_barcode(unit)
        batch = (
            Batch.objects.filter(pk=request.get("batch")).first() if request.get("batch") else None
        )
        price = catalog.price_of(unit, batch.cost_per_base if batch else None)
        label = {
            "name": unit.item.name,
            "unit": unit.unit.name,
            "price": price,
            "barcode": code,
            "barcode_svg": barcode_svg(code),
            "series": batch.series if batch else "",
            "expiry_date": batch.expiry_date if batch else None,
            "article": unit.item.article,
        }
        labels.extend([label] * max(1, min(int(request.get("copies") or 1), MAX_LABELS)))
        if len(labels) >= MAX_LABELS:
            break
    return {"labels": labels[:MAX_LABELS]}


def sample_context() -> dict[str, Any]:
    from decimal import Decimal

    return {
        "labels": [
            {
                "name": "Витамины 8в1, 216 таб.",
                "unit": "упак.",
                "price": Decimal("600"),
                "barcode": "2000000000015",
                "barcode_svg": barcode_svg("2000000000015"),
                "series": "A-2027",
                "expiry_date": None,
                "article": "VT-216",
            }
        ]
    }


def render(requests: list[LabelRequest], template: Any) -> bytes:
    return core.render_print(template, label_context(requests))
