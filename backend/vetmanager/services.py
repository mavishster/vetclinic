"""Перенос из VetManager: публичный вход модуля.

Отвечает за: перенос справочников, товаров и услуг, клиентов, питомцев, медкарт и счетов.
Переносим по шагам и повторяемо: уже перенесённое не задваивается (таблица Imported).

Бизнес-правила живут здесь, а не в моделях и не в API (ENGINEERING.md).
"""

import contextlib
import html
import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction
from django.utils import timezone

from catalog import services as catalog
from catalog.models import Item, ItemGroup, ItemUnit, Kind, Unit
from clients import services as clients_services
from clients.models import Breed, City, Client, ClientContract, Pet, Species, Street
from core import services as core
from core.html import clean
from core.models import User
from medical.models import Visit
from scheduling.models import VisitPurpose
from staff.models import Employee, Position
from vetmanager import client
from vetmanager.models import Imported

VetManagerError = client.VetManagerError

# Шаги переноса — по порядку: каждый следующий опирается на предыдущие.
# Код страны для телефонов без него (в VetManager он хранится отдельно и часто пуст).
COUNTRY_CODE = "+996"

STEPS = [
    ("units", "Единицы измерения"),
    ("item_groups", "Группы прайса"),
    ("items", "Товары и услуги"),
    ("species", "Виды и породы"),
    ("clients", "Клиенты"),
    ("pets", "Питомцы"),
    ("doctors", "Врачи"),
    ("diagnoses", "Диагнозы"),
    ("visits", "Медкарты"),
]


@dataclass
class StepResult:
    step: str
    title: str
    total: int = 0  # записей в VetManager
    created: int = 0
    updated: int = 0
    skipped: int = 0  # уже переносили
    errors: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        parts = [f"всего {self.total}", f"добавлено {self.created}"]
        if self.updated:
            parts.append(f"обновлено {self.updated}")
        if self.skipped:
            parts.append(f"уже было {self.skipped}")
        if self.errors:
            parts.append(f"с ошибками {len(self.errors)}")
        return ", ".join(parts)


def _plain(value: str) -> str:
    """Название из VetManager без разметки: в справочниках попадается «<br/>Спленит»."""
    without_tags = re.sub(r"<[^>]*>", " ", value)
    cleaned = " ".join(html.unescape(without_tags).split()).strip(" .,;-—")
    return cleaned[:1].upper() + cleaned[1:] if cleaned else ""


def _text(row: dict[str, Any], *names: str) -> str:
    """Значение по первому попавшемуся имени поля: у разных версий API они разные."""
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _flag(row: dict[str, Any], name: str, default: bool = False) -> bool:
    """Признак VetManager: 1/0 (иногда строкой)."""
    value = row.get(name)
    if value in (None, ""):
        return default
    return str(value).strip().lower() in ("1", "true", "yes")


def _positive(value: Any) -> Decimal | None:
    """Число больше нуля или None: в VetManager «не задано» хранится как 0.0000000000."""
    number = _decimal(value)
    return number if number is not None and number > 0 else None


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _link(kind: str, external_id: str) -> Imported | None:
    return Imported.objects.filter(kind=kind, external_id=str(external_id)).first()


def _remember(kind: str, external_id: str, target_id: Any) -> None:
    Imported.objects.update_or_create(
        kind=kind, external_id=str(external_id), defaults={"target_id": target_id}
    )


def imported_count(kind: str) -> int:
    return Imported.objects.filter(kind=kind).count()


# --- Сведение названий ----------------------------------------------------------------

# Как в VetManager пишут единицы → наша единица. Сравнение без точек, пробелов и регистра.
UNIT_SYNONYMS = {
    "шт.": ("шт", "штука", "штуки", "штук", "pcs", "ед", "единица"),
    "фл.": ("фл", "флакон", "флакона", "флаконов", "флак"),
    "таб.": ("таб", "табл", "таблетка", "таблетки", "таблеток"),
    "упак.": ("уп", "упак", "упаковка", "упаковки", "упаковок", "пачка"),
    "амп.": ("амп", "ампула", "ампулы", "ампул"),
    "капс.": ("капс", "капсула", "капсулы", "капсул"),
    "доза": ("доз", "дозы", "дозировка"),
    "усл.": ("усл", "услуга", "услуги", "процедура", "работа"),
    "мл": ("миллилитр", "ml"),
    "л": ("литр", "литры"),
    "г": ("гр", "грамм", "граммы", "g"),
    "кг": ("килограмм", "килограммы", "kg"),
}


def simplify(name: str) -> str:
    """«Шт.» и « штука » — к одному виду: без точек, пробелов, регистра и «ё»."""
    return name.lower().replace("ё", "е").replace(".", "").replace(" ", "").strip()


def _same_name(queryset: Any, name: str) -> Any:
    """Запись справочника с таким же названием — без учёта точек, пробелов и регистра."""
    simple = simplify(name)
    return next((row for row in queryset if simplify(row.name) == simple), None)


def match_unit(name: str) -> Unit | None:
    """Наша единица для названия из VetManager (по словарю или по самому названию)."""
    simple = simplify(name)
    for ours, variants in UNIT_SYNONYMS.items():
        if simple == simplify(ours) or simple in variants:
            found: Unit | None = _same_name(Unit.objects.all(), ours)
            if found is not None:
                return found
    matched: Unit | None = _same_name(Unit.objects.all(), name)
    return matched


def used_units(goods: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Только единицы, которые встречаются в товарах и их ценах, — без мусора справочника.

    Названия берутся из самого ответа по товарам (VetManager отдаёт их вместе с позицией),
    поэтому отдельный справочник единиц не нужен.
    """
    goods = _goods_rows() if goods is None else goods
    found: dict[str, dict[str, Any]] = {}
    for row in goods:
        storage = row.get("unitStorage")
        if isinstance(storage, dict) and storage.get("id"):
            found.setdefault(str(storage["id"]), storage)
        for price in row.get("goodSaleParams") or []:
            unit_id = str(price.get("unit_sale_id") or "")
            if unit_id and unit_id not in found:
                found[unit_id] = {"id": unit_id, "title": ""}
    unknown = [unit_id for unit_id, row in found.items() if not row.get("title")]
    if unknown:  # единица продажи, которой нет среди единиц учёта, — берём из справочника
        for row in client.fetch("Unit"):
            if str(row.get("id")) in unknown:
                found[str(row["id"])] = row
    return [row for row in found.values() if _text(row, "title", "name")]


def unit_plan() -> list[dict[str, Any]]:
    """Что с чем сведётся — показываем до переноса, чтобы можно было проверить."""
    plan: dict[str, dict[str, Any]] = {}
    for row in used_units():
        name = _text(row, "title", "name")
        if not name:
            continue
        ours = match_unit(name)
        key = ours.name if ours is not None else name
        entry = plan.setdefault(key, {"target": key, "is_new": ours is None, "sources": []})
        if name not in entry["sources"]:
            entry["sources"].append(name)
    return sorted(plan.values(), key=lambda row: row["target"])


# --- Шаги -----------------------------------------------------------------------------


@transaction.atomic
def import_units(rows: list[dict[str, Any]] | None = None) -> StepResult:
    """Единицы измерения VetManager → наши.

    В VetManager они часто задвоены («шт», «шт.», «штука») — все такие варианты
    сводятся к одной нашей единице; новая заводится, только если похожей нет.
    """
    rows = used_units() if rows is None else rows
    result = StepResult("units", "Единицы измерения", total=len(rows))
    for row in rows:
        name = _text(row, "title", "name")
        if not name:
            result.errors.append(f"Единица {row.get('id')}: нет названия.")
            continue
        if _link("unit", row["id"]):
            result.skipped += 1
            continue
        unit = match_unit(name)
        if unit is None:
            unit = Unit.objects.create(name=name[:20])
            result.created += 1
        else:
            result.updated += 1
        _remember("unit", row["id"], unit.pk)
    return result


@transaction.atomic
def import_item_groups(rows: list[dict[str, Any]] | None = None) -> StepResult:
    """Группы товаров VetManager → группы прайса.

    Вид берётся из самой группы (is_service), наценка группы переносится как есть.
    Названия сводятся к уже имеющимся: «Препараты» и «препараты » — одна группа.
    """
    rows = client.fetch("GoodGroup") if rows is None else rows
    result = StepResult("item_groups", "Группы прайса", total=len(rows))
    for row in rows:
        external_id = str(row.get("id") or "")
        name = _text(row, "title", "name")[:150]
        if not name:
            result.errors.append(f"Группа {external_id}: нет названия.")
            continue
        if _link("item_group", external_id):
            result.skipped += 1
            continue
        kind = Kind.SERVICE if _flag(row, "is_service") else Kind.GOODS
        markup = _positive(row.get("markup"))
        group = _same_name(ItemGroup.objects.filter(kind=kind), name)
        if group is None:
            group = ItemGroup.objects.create(name=name, kind=kind, markup_percent=markup)
            result.created += 1
        else:
            # Свою наценку не затираем: переносим, только если у нас её нет.
            if markup is not None and group.markup_percent is None:
                group.markup_percent = markup
                group.save(update_fields=["markup_percent"])
            result.updated += 1
        _remember("item_group", external_id, group.pk)
    return result


def _goods_rows() -> list[dict[str, Any]]:
    """Товары и услуги: VetManager отдаёт их вместе с группой, единицей и ценами."""
    return client.fetch("Good")


def _sale_params(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Действующие цены позиции: без удалённых и без прежних (is_last)."""
    rows = [p for p in row.get("goodSaleParams") or [] if isinstance(p, dict)]
    active = [
        p
        for p in rows
        if str(p.get("status", "active")).lower() == "active" and _flag(p, "is_last", default=True)
    ]
    return active or rows


@transaction.atomic
def import_items(goods: list[dict[str, Any]] | None = None) -> StepResult:
    """Товары и услуги VetManager → прайс: позиция, единицы продажи и цены.

    Услуга или товар — по группе позиции (is_service); складской учёт — по
    is_warehouse_account. Себестоимость (prime_cost) и наценка переносятся, ноль
    у VetManager означает «не задано».
    """
    goods = _goods_rows() if goods is None else goods
    result = StepResult("items", "Товары и услуги", total=len(goods))
    for row in goods:
        external_id = str(row.get("id") or "")
        name = _text(row, "title", "name")
        if not name:
            result.errors.append(f"Позиция {external_id}: нет названия.")
            continue
        if _link("item", external_id):
            result.skipped += 1
            continue
        nested = row.get("group")
        group_row: dict[str, Any] = nested if isinstance(nested, dict) else {}
        kind = Kind.SERVICE if _flag(group_row, "is_service") else Kind.GOODS
        group = _group_for(row, group_row, kind)
        base_unit = _unit_for(row.get("unitStorage"), row.get("unit_storage_id"), kind)
        item = Item(
            kind=kind,
            name=name[:200],
            group=group,
            base_unit=base_unit,
            article=_text(row, "code", "article")[:50],
            barcode=_text(row, "barcode")[:50],
            description=_text(row, "description"),
            manual_cost=_positive(row.get("prime_cost")),
            stock_tracked=_flag(row, "is_warehouse_account", default=True) and kind == Kind.GOODS,
            for_sale=_flag(row, "is_for_sale", default=True),
            combo_only=_flag(row, "for_combination"),
            is_call=_flag(row, "is_call"),
            is_active=_flag(row, "is_active", default=True),
        )
        try:
            saved = catalog.save_item(item, _units_for(_sale_params(row), base_unit))
        except catalog.CatalogError as error:
            result.errors.append(f"«{name}»: {error}")
            continue
        _remember("item", external_id, saved.pk)
        result.created += 1
    return result


def _group_for(row: dict[str, Any], group_row: dict[str, Any], kind: str) -> ItemGroup:
    """Группа позиции: уже перенесённая, иначе по названию, иначе «Без группы»."""
    link = _link("item_group", str(row.get("group_id") or ""))
    group = ItemGroup.objects.filter(pk=link.target_id).first() if link else None
    if group is not None and group.kind == kind:
        return group
    name = _text(group_row, "title", "name") or "Без группы (VetManager)"
    return _same_name(ItemGroup.objects.filter(kind=kind), name) or ItemGroup.objects.create(
        name=name[:150], kind=kind, markup_percent=_positive(group_row.get("markup"))
    )


def _unit_for(unit_row: Any, external_id: Any, kind: str) -> Unit:
    """Единица учёта: перенесённая, по названию из ответа, иначе «шт.» или «усл.»."""
    link = _link("unit", str(external_id or ""))
    unit = Unit.objects.filter(pk=link.target_id).first() if link else None
    if unit is not None:
        return unit
    name = _text(unit_row, "title", "name") if isinstance(unit_row, dict) else ""
    found = match_unit(name) if name else None
    if found is not None:
        return found
    if name:
        return Unit.objects.create(name=name[:20])
    fallback = "усл." if kind == Kind.SERVICE else "шт."
    return _same_name(Unit.objects.all(), fallback) or Unit.objects.create(name=fallback)


def _limits(row: dict[str, Any], price: Decimal | None) -> tuple[Decimal | None, Decimal | None]:
    """Границы цены из VetManager — только если они не спорят с самой ценой.

    В выгрузке встречаются границы, в которые её же цена не укладывается (например,
    цену подняли, а максимум остался прежним). Такие границы не переносим: иначе
    позиция вовсе не перенесётся, а цена важнее.
    """
    low, high = _positive(row.get("min_price")), _positive(row.get("max_price"))
    if low is not None and high is not None and low > high:
        return None, None
    if price is not None:
        if low is not None and price < low:
            low = None
        if high is not None and price > high:
            high = None
    return low, high


def _units_for(price_rows: list[dict[str, Any]], base_unit: Unit) -> list[catalog.UnitData]:
    """Единицы продажи с ценами. Цена по наценке (price_formation) переносится наценкой."""
    prepared: list[catalog.UnitData] = []
    seen: set[Any] = set()
    for row in price_rows:
        link = _link("unit", str(row.get("unit_sale_id") or ""))
        unit = (Unit.objects.filter(pk=link.target_id).first() if link else None) or base_unit
        if unit.pk in seen:
            continue
        seen.add(unit.pk)
        ratio = _decimal(row.get("coefficient")) or Decimal("1")
        if ratio == 1 and unit.pk != base_unit.pk:
            # В VetManager у позиции бывает своя единица продажи с коэффициентом 1
            # («упак.» при учёте в «шт.»): это та же единица, другого названия.
            # Заводить её отдельной нельзя — продажа 1 упак. списывала бы 1 шт.
            unit = base_unit
            if unit.pk in seen:
                continue
            seen.add(unit.pk)
        by_markup = str(row.get("price_formation", "")).lower() == "markup"
        markup = _positive(row.get("markup"))
        limits = _limits(row, None if by_markup else _decimal(row.get("price")))
        prepared.append(
            {
                "unit": unit.pk,
                "ratio": ratio if unit.pk != base_unit.pk and ratio > 0 else Decimal("1"),
                "pricing": ItemUnit.Pricing.MARKUP if by_markup else ItemUnit.Pricing.FIXED,
                "price": None if by_markup else (_decimal(row.get("price")) or Decimal("0")),
                "markup_percent": markup if by_markup else None,
                "price_min": limits[0],
                "price_max": limits[1],
                "barcode": _text(row, "barcode")[:50],
                "for_sale": True,
            }
        )
    if not prepared:
        prepared.append(
            {
                "unit": base_unit.pk,
                "ratio": Decimal("1"),
                "pricing": ItemUnit.Pricing.FIXED,
                "price": Decimal("0"),
                "for_sale": True,
            }
        )
    return prepared


# --- Клиенты и питомцы ----------------------------------------------------------------

# Пол в VetManager одним полем, вместе со стерилизацией; у нас это пол и отдельный
# признак «стерилизован / кастрирован» — так принято и в других системах.
_SEX = {
    "male": (Pet.Sex.MALE, False),
    "м": (Pet.Sex.MALE, False),
    "самец": (Pet.Sex.MALE, False),
    "мальчик": (Pet.Sex.MALE, False),
    "кастрирован": (Pet.Sex.MALE, True),
    "кастрат": (Pet.Sex.MALE, True),
    "castrated": (Pet.Sex.MALE, True),
    "female": (Pet.Sex.FEMALE, False),
    "ж": (Pet.Sex.FEMALE, False),
    "самка": (Pet.Sex.FEMALE, False),
    "девочка": (Pet.Sex.FEMALE, False),
    "стерилизована": (Pet.Sex.FEMALE, True),
    "стерилизована(ый)": (Pet.Sex.FEMALE, True),
    "sterilized": (Pet.Sex.FEMALE, True),
}


def _sex_of(row: dict[str, Any]) -> tuple[str, bool]:
    """Пол и признак стерилизации из одного поля VetManager."""
    value = simplify(_text(row, "sex", "gender"))
    return _SEX.get(value, (Pet.Sex.UNKNOWN, False))


def _moment(value: Any) -> Any:
    """Дата и время из VetManager: «2026-11-12 14:30:00»; нули и пустое — None."""
    from datetime import datetime

    text = str(value or "").strip()
    if not text or text.startswith(("0000", "1970-01-01")):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            naive = datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
        return timezone.make_aware(naive, timezone.get_current_timezone())
    return None


def _date(value: Any) -> Any:
    """Дата из VetManager: «2019-05-17» или «2019-05-17 00:00:00»; нули — пусто."""
    text = str(value or "").strip()
    if not text or text.startswith(("0000", "1970-01-01")):
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


@transaction.atomic
def import_species(
    types: list[dict[str, Any]] | None = None, breeds: list[dict[str, Any]] | None = None
) -> StepResult:
    """Виды животных и породы VetManager → наши справочники."""
    types = client.fetch("PetType") if types is None else types
    breeds = client.fetch("Breed") if breeds is None else breeds
    result = StepResult("species", "Виды и породы", total=len(types) + len(breeds))
    for row in types:
        name = _text(row, "title", "name")[:100]
        if not name or _link("species", str(row.get("id") or "")):
            result.skipped += 1 if name else 0
            continue
        species = _same_name(Species.objects.all(), name)
        if species is None:
            species = Species.objects.create(name=name)
            result.created += 1
        else:
            result.updated += 1
        _remember("species", row["id"], species.pk)
    for row in breeds:
        name = _text(row, "title", "name")[:100]
        link = _link("species", str(row.get("pet_type_id") or ""))
        species = Species.objects.filter(pk=link.target_id).first() if link else None
        if not name or species is None:
            result.errors.append(f"Порода {row.get('id')}: не нашёлся вид животного.")
            continue
        if _link("breed", str(row["id"])):
            result.skipped += 1
            continue
        breed = _same_name(Breed.objects.filter(species=species), name)
        if breed is None:
            breed = Breed.objects.create(name=name, species=species)
            result.created += 1
        else:
            result.updated += 1
        _remember("breed", row["id"], breed.pk)
    return result


def _phone_number(number: str, prefix: str) -> str:
    """Телефон в международном виде: 555287246 → +996555287246.

    В VetManager код страны хранится отдельно и часто пуст, поэтому к местным
    девятизначным номерам подставляем код страны клиники.
    """
    digits = "".join(sign for sign in number if sign.isdigit() or sign == "+")
    if digits.startswith("+"):
        return digits
    if digits.startswith("00"):
        return f"+{digits[2:]}"
    if prefix:
        prefix = prefix if prefix.startswith("+") else f"+{prefix.lstrip('0')}"
        return f"{prefix}{digits.lstrip('0')}"
    if len(digits) == 9:  # местный номер без кода страны
        return f"{COUNTRY_CODE}{digits}"
    if len(digits) in (10, 11) and digits.startswith("0"):  # 0555287246
        return f"{COUNTRY_CODE}{digits.lstrip('0')}"
    return digits


def _phones(row: dict[str, Any]) -> list[clients_services.PhoneData]:
    """Телефоны клиента: мобильный — основной, домашний и рабочий — следом."""
    prefix = _text(row, "phone_prefix")
    found: list[clients_services.PhoneData] = []
    for source, kind in (("cell_phone", "mobile"), ("home_phone", "home"), ("work_phone", "work")):
        number = _phone_number(_text(row, source), prefix)
        if not number or len(number) < 7:
            continue
        found.append({"number": number[:30], "kind": kind, "is_primary": not found})
    return found


@transaction.atomic
def import_clients(rows: list[dict[str, Any]] | None = None) -> StepResult:
    """Клиенты VetManager → карточки клиентов с телефонами.

    Чёрный список, отказ от рассылки, скидка и номер по журналу переносятся;
    баланс не переносится — он складывается из счетов и оплат.
    """
    rows = client.fetch("Client") if rows is None else rows
    result = StepResult("clients", "Клиенты", total=len(rows))
    streets = _vetmanager_streets()
    for row in rows:
        external_id = str(row.get("id") or "")
        last_name = _text(row, "last_name")
        if not last_name:
            last_name = (
                _text(row, "first_name") or _text(row, "cell_phone") or f"Без имени {external_id}"
            )
        link = _link("client", external_id)
        existing = Client.objects.filter(pk=link.target_id).first() if link else None
        if link is not None and existing is None:
            result.skipped += 1  # карточку удалили у нас — заново не заводим
            continue
        city = _city_for(row, streets)
        street = _street_for(row, city, streets)
        house = " ".join(part for part in (_text(row, "address"), _text(row, "apartment")) if part)
        status = Client.Status.ACTIVE
        if str(row.get("status", "")).upper() in ("DELETED", "INACTIVE", "ARCHIVE"):
            status = Client.Status.INACTIVE
        record = existing or Client()
        _fill(
            record,
            last_name=last_name[:100],
            first_name=_text(row, "first_name")[:100],
            middle_name=_text(row, "middle_name")[:100],
            passport=_text(row, "passport_series")[:50],
            city=city,
            street=street,
            house=house[:100],
            zip_code=_text(row, "zip")[:10],
            email=_text(row, "email")[:254] if "@" in _text(row, "email") else "",
            discount_percent=_positive(row.get("discount")) or Decimal("0"),
            journal_number=_text(row, "number_of_journal")[:50],
            no_mailing=_flag(row, "unsubscribe"),
            in_blacklist=_flag(row, "in_blacklist"),
            description=_text(row, "note"),
            status=status,
        )
        try:
            saved = clients_services.save_client(
                record, _phones(row), number=int(external_id) if external_id.isdigit() else None
            )
        except clients_services.ClientError as error:
            result.errors.append(f"«{last_name}»: {error}")
            continue
        _remember("client", external_id, saved.pk)
        _contract_mark(saved, row)
        if existing is None:
            result.created += 1
        else:
            result.updated += 1  # повторный перенос: подтянули изменения из VetManager
    return result


def _contract_mark(saved: Client, row: dict[str, Any]) -> None:
    """В карточке клиента VetManager есть только отметка «договор есть», без номера.
    Заводим договор «б/н» от даты регистрации, чтобы отметка не потерялась; повторный
    перенос и договоры, уже заведённые у нас, его не задваивают."""
    if not _flag(row, "has_contract") or saved.contracts.exists():
        return
    ClientContract.objects.create(
        client=saved,
        number="б/н",
        date=_date(row.get("date_register")) or timezone.localdate(),
        comment="Перенесено из VetManager: отметка «договор есть», номер там не хранится",
    )


def _vetmanager_streets() -> dict[str, dict[str, Any]]:
    """Улицы VetManager по их номеру: в карточке клиента хранится только номер улицы."""
    try:
        return {str(row.get("id")): row for row in client.fetch("Street")}
    except VetManagerError:
        return {}


def _nested(row: dict[str, Any], name: str) -> dict[str, Any]:
    """Вложенная запись из ответа VetManager (city_data, street_data) — или пусто."""
    value = row.get(name)
    return value if isinstance(value, dict) else {}


def _city_for(row: dict[str, Any], streets: dict[str, dict[str, Any]] | None = None) -> Any:
    """Город клиента. В VetManager текстовое поле city обычно пусто: город выбран
    из справочника и приходит вложенной записью city_data (или вместе с улицей)."""
    street = _nested(row, "street_data") or (streets or {}).get(str(row.get("street_id") or ""), {})
    name = (
        _text(_nested(row, "city_data"), "title", "name")
        or _text(row, "city")
        or _text(_nested(street, "city"), "title", "name")
    )
    if not name:
        return None
    return _same_name(City.objects.all(), name) or City.objects.create(name=name[:100])


# Тип улицы VetManager отдаёт английским словом — в название пишем по-русски.
STREET_KINDS = {
    "street": "улица",
    "microdistrict": "микрорайон",
    "district": "район",
    "lane": "переулок",
    "avenue": "проспект",
    "prospect": "проспект",
    "boulevard": "бульвар",
    "highway": "шоссе",
    "square": "площадь",
    "passage": "проезд",
    "drive": "проезд",
    "embankment": "набережная",
    "quarter": "квартал",
    "village": "село",
    "residential": "жилмассив",
    "blind_alley": "тупик",
    "alley": "аллея",
}


def _street_for(row: dict[str, Any], city: Any, streets: dict[str, dict[str, Any]]) -> Any:
    """Улица клиента: приходит вложенной записью street_data, иначе берётся из
    справочника улиц VetManager по номеру.

    Тип улицы («улица», «микрорайон») сохраняем в названии, как в VetManager.
    """
    source = _nested(row, "street_data") or streets.get(str(row.get("street_id") or ""))
    if not source or city is None:
        return None
    name = _text(source, "title", "name")
    if not name:
        return None
    kind = _text(source, "type_title", "street_type", "type")
    kind = STREET_KINDS.get(kind.lower(), kind)
    full = f"{kind} {name}".strip() if kind and kind.lower() not in name.lower() else name
    found = _same_name(Street.objects.filter(city=city), full)
    return found or Street.objects.create(name=full[:100], city=city)


def _fill(record: Any, **values: Any) -> Any:
    """Заполнить поля записи — новой или уже перенесённой (повторный перенос)."""
    for name, value in values.items():
        setattr(record, name, value)
    return record


def _fallback_species() -> Species:
    name = "Не указан"
    return _same_name(Species.objects.all(), name) or Species.objects.create(name=name)


def _fallback_breed(species: Species) -> Breed:
    name = "Не указана"
    return _same_name(Breed.objects.filter(species=species), name) or Breed.objects.create(
        name=name, species=species
    )


@transaction.atomic
def import_pets(rows: list[dict[str, Any]] | None = None) -> StepResult:
    """Питомцы VetManager → карточки питомцев их владельцев.

    Вид и порода берутся из перенесённых справочников; если их нет — «Не указан».
    Умершие переносятся со статусом «умер», вес — первой записью истории веса.
    """
    rows = client.fetch("Pet") if rows is None else rows
    result = StepResult("pets", "Питомцы", total=len(rows))
    for row in rows:
        external_id = str(row.get("id") or "")
        name = _text(row, "alias", "name")[:100] or f"Без клички {external_id}"
        owner_link = _link("client", str(row.get("owner_id") or ""))
        owner = Client.objects.filter(pk=owner_link.target_id).first() if owner_link else None
        if owner is None:
            result.errors.append(f"«{name}»: владелец не перенесён — сначала перенесите клиентов.")
            continue
        link = _link("pet", external_id)
        existing = Pet.objects.filter(pk=link.target_id).first() if link else None
        if link is not None and existing is None:
            result.skipped += 1  # карточку удалили у нас — заново не заводим
            continue
        species_link = _link("species", str(row.get("type_id") or ""))
        species = (
            Species.objects.filter(pk=species_link.target_id).first() if species_link else None
        )
        species = species or _fallback_species()
        breed_link = _link("breed", str(row.get("breed_id") or ""))
        breed = Breed.objects.filter(pk=breed_link.target_id).first() if breed_link else None
        if breed is None or breed.species_id != species.pk:
            breed = _fallback_breed(species)
        death = _date(row.get("deathdate"))
        sex, sterilized = _sex_of(row)
        status = Pet.Status.ACTIVE
        if death:
            status = Pet.Status.DEAD
        elif str(row.get("status", "ACTIVE")).upper() in ("DELETED", "INACTIVE", "ARCHIVE", "0"):
            status = Pet.Status.INACTIVE  # в VetManager питомец не активен
        pet = _fill(
            existing or Pet(),
            owner=owner,
            name=name,
            species=species,
            breed=breed,
            sex=sex,
            sterilized=sterilized,
            birth_date=_date(row.get("birthday")),
            chip_number=_text(row, "chip_number")[:50],
            lab_number=_text(row, "lab_number")[:50],
            notes=" ".join(part for part in (_text(row, "note"), _text(row, "deathnote")) if part),
            status=status,
            death_date=death,
        )
        try:
            saved = clients_services.save_pet(pet)
        except clients_services.ClientError as error:
            result.errors.append(f"«{name}»: {error}")
            continue
        weight = _positive(row.get("weight"))
        if weight is not None:
            # Вес из карточки VetManager — первой записью истории веса (дата регистрации).
            with contextlib.suppress(clients_services.ClientError):
                clients_services.add_weight(saved, weight, _date(row.get("date_register")))
        _remember("pet", external_id, saved.pk)
        if existing is None:
            result.created += 1
        else:
            result.updated += 1  # повторный перенос: подтянули изменения из VetManager
    return result


# --- Врачи и медкарты -----------------------------------------------------------------

# Цель обращения в VetManager задаётся типом приёма; что не узнали — «Первичный».
DEFAULT_PURPOSE = "Первичный"
VISITS_BATCH = 200  # по столько приёмов за раз: обрыв связи не отменит перенесённое
TRANSFER_DOCTOR = "Врач (перенос из VetManager)"


def _full_name(row: dict[str, Any]) -> str:
    parts = [_text(row, "last_name"), _text(row, "first_name"), _text(row, "middle_name")]
    return " ".join(part for part in parts if part)


# Как латиницей записать логин: по фамилии («Иванова» → ivanova).
_TRANSLIT = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "c",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def _login_for(last_name: str, first_name: str) -> str:
    """Свободный логин латиницей: ivanova, при совпадении — ivanova2."""
    base = "".join(
        _TRANSLIT.get(letter, letter) for letter in last_name.lower() if letter.isalnum()
    )
    base = "".join(letter for letter in base if letter.isascii()) or "doctor"
    if User.objects.filter(username__iexact=base).exists() and first_name:
        initial = _TRANSLIT.get(first_name[:1].lower(), first_name[:1].lower())
        base = f"{base}{initial}" if initial.isascii() else base
    login, number = base, 1
    while User.objects.filter(username__iexact=login).exists():
        number += 1
        login = f"{base}{number}"
    return login


def _doctor_phone(row: dict[str, Any]) -> str:
    """Телефон врача: в VetManager он лежит в одном из нескольких полей."""
    for name in ("phone", "cell_phone", "mobile_phone", "mobile", "tel", "work_phone"):
        number = _phone_number(_text(row, name), _text(row, "phone_prefix"))
        if len(number) >= 7:
            return number
    return ""


def _position_for(row: dict[str, Any]) -> Position:
    """Должность из VetManager, иначе «Врач»."""
    nested = row.get("position")
    name = (
        _text(nested, "title", "name")
        if isinstance(nested, dict)
        else _text(row, "position", "post")
    )
    name = name[:100] or "Врач"
    return _same_name(Position.objects.all(), name) or Position.objects.create(name=name)


def _match_employee(row: dict[str, Any], employees: list[User]) -> User | None:
    """Наш сотрудник с такой же фамилией (и именем, если оно есть у обоих)."""
    last_name, first_name = _text(row, "last_name"), _text(row, "first_name")
    return next(
        (
            user
            for user in employees
            if simplify(user.last_name) == simplify(last_name)
            and (
                not first_name
                or not user.first_name
                or simplify(user.first_name)[:1] == simplify(first_name)[:1]
            )
        ),
        None,
    )


def _doctors_with_visits() -> set[str] | None:
    """Врачи, у которых есть приёмы. None — если список приёмов недоступен."""
    try:
        return {str(row.get("user_id") or "") for row in client.fetch("Admission")} - {""}
    except VetManagerError:
        return None


def doctor_rows(
    rows: list[dict[str, Any]] | None = None, only_with_visits: bool = True
) -> list[dict[str, Any]]:
    """Врачи VetManager и что с ними будет: связать с нашим сотрудником или завести."""
    rows = client.fetch("User") if rows is None else rows
    with_visits = _doctors_with_visits() if only_with_visits else None
    employees = list(User.objects.all())
    plan = []
    for row in rows:
        last_name = _text(row, "last_name")
        if not last_name:
            continue
        if with_visits is not None and str(row.get("id")) not in with_visits:
            continue  # администраторы и кассиры в медкартах не нужны
        found = _match_employee(row, employees)
        plan.append(
            {
                "external_id": str(row.get("id") or ""),
                "name": _full_name(row),
                "position": _position_name(row),
                "active": _flag(row, "is_active", default=True),
                "action": "link" if found is not None else "create",
                "login": found.username
                if found is not None
                else _login_for(last_name, _text(row, "first_name")),
                "row": row,
            }
        )
    return plan


def _position_name(row: dict[str, Any]) -> str:
    nested = row.get("position")
    name = (
        _text(nested, "title", "name")
        if isinstance(nested, dict)
        else _text(row, "position", "post")
    )
    return name or "Врач"


def _fill_contacts(user: User, row: dict[str, Any]) -> None:
    """Телефон и почта у уже заведённого сотрудника: заполняем, только если их нет."""
    email = _text(row, "email")
    if not user.email and "@" in email:
        user.email = email[:254]
        user.save(update_fields=["email"])
    employee = Employee.objects.filter(user=user).first()
    phone = _doctor_phone(row)
    if employee is not None and not employee.phone and phone:
        employee.phone = phone[:30]
        employee.save(update_fields=["phone"])


@transaction.atomic
def import_doctors(
    rows: list[dict[str, Any]] | None = None, only_with_visits: bool = True
) -> StepResult:
    """Врачи VetManager → наши сотрудники.

    Кого нашли по фамилии и имени — связываем. Кого нет — заводим: должность из
    VetManager (иначе «Врач»), логин латиницей, уволенные — неактивными.
    Пароль не задаётся и права не выдаются: войти нельзя, пока администратор
    не задаст пароль и не назначит роль.
    """
    plan = doctor_rows(rows, only_with_visits)
    result = StepResult("doctors", "Врачи", total=len(plan))
    for entry in plan:
        row = entry["row"]
        link = _link("doctor", entry["external_id"])
        if link is not None:
            # Врач уже перенесён: заново не заводим, но пустые контакты дозаполняем —
            # телефон и почту могли добавить в VetManager после переноса.
            existing = User.objects.filter(pk=link.target_id).first()
            if existing is not None:
                _fill_contacts(existing, row)
            result.skipped += 1
            continue
        if entry["action"] == "link":
            found = _match_employee(row, list(User.objects.all()))
            if found is not None:
                _fill_contacts(found, row)  # заполняем пустое, своё не затираем
                _remember("doctor", entry["external_id"], found.pk)
                result.updated += 1
                continue
        email = _text(row, "email")
        user = User.objects.create(
            username=entry["login"],
            last_name=_text(row, "last_name")[:150],
            first_name=_text(row, "first_name")[:150],
            middle_name=_text(row, "middle_name")[:150],
            email=email[:254] if "@" in email else "",
            is_active=entry["active"],
        )
        user.set_unusable_password()  # вход закрыт, пока администратор не задаст пароль
        user.save(update_fields=["password"])
        employee = Employee.objects.filter(user=user).first() or Employee(user=user)
        employee.position = _position_for(row)
        employee.phone = _doctor_phone(row)[:30]
        employee.in_schedule = entry["active"]
        employee.save()
        _remember("doctor", entry["external_id"], user.pk)
        result.created += 1
    return result


def _transfer_doctor() -> User:
    """Учётная запись, на которую ложатся приёмы врачей, которых не нашли."""
    user = User.objects.filter(username="vetmanager-transfer").first()
    if user is None:
        user = User.objects.create_user(
            username="vetmanager-transfer", last_name=TRANSFER_DOCTOR, is_active=False
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user


def _purpose_for(
    row: dict[str, Any], titles: dict[str, str], default: VisitPurpose
) -> VisitPurpose:
    """Цель обращения: по значению admission_type в разделе «Тип приёма»."""
    name = titles.get(str(row.get("admission_type") or row.get("type_id") or ""), "")
    if not name:
        return default
    found = _same_name(VisitPurpose.objects.all(), name)
    return found or VisitPurpose.objects.create(name=name[:100])


@transaction.atomic
def import_visit_purposes(rows: list[dict[str, Any]] | None = None) -> StepResult:
    """Типы приёмов VetManager → цели обращения.

    Они лежат в общем справочнике ComboManualItem (раздел «Тип приёма»).
    """
    rows = _combo_items() if rows is None else rows
    rows = [row for row in rows if _manual_name(row) in PURPOSE_MANUAL or not _manual_name(row)]
    result = StepResult("visit_purposes", "Цели обращения", total=len(rows))
    for row in rows:
        name = _plain(_text(row, "title"))[:100]
        if not name or _link("visit_purpose", str(row.get("id") or "")):
            continue
        purpose = _same_name(VisitPurpose.objects.all(), name)
        if purpose is None:
            purpose = VisitPurpose.objects.create(name=name)
            result.created += 1
        else:
            result.updated += 1
        _remember("visit_purpose", row["id"], purpose.pk)
    return result


# Разделы общего справочника VetManager: в медкарте хранится не номер элемента,
# а его «значение» (value) внутри своего раздела.
PURPOSE_MANUAL = ("admission_type",)
RESULT_MANUAL = ("meet_result", "admission_result", "visit_result")


def _manual_name(row: dict[str, Any]) -> str:
    """Имя раздела справочника, которому принадлежит элемент."""
    nested = row.get("comboManualName")
    return _text(nested, "name") if isinstance(nested, dict) else ""


def _combo_titles(items: list[dict[str, Any]], manuals: tuple[str, ...]) -> dict[str, str]:
    """«Значение элемента → название» внутри нужного раздела справочника.

    В медкарте admission_type: 3 — это value, а не номер элемента: по номеру
    подставлялось название из чужого раздела.
    """
    return {
        str(row.get("value")): _plain(_text(row, "title"))
        for row in items
        if _manual_name(row) in manuals and row.get("value") not in (None, "")
    }


def _combo_items() -> list[dict[str, Any]]:
    """Элементы справочников VetManager (типы приёмов, результаты): один общий список."""
    try:
        return client.fetch("ComboManualItem")
    except VetManagerError:
        return []


def _medical_rows() -> list[dict[str, Any]]:
    """Медкарты VetManager. Если раздела нет (старая версия) — приёмы."""
    try:
        return client.fetch("MedicalCards")
    except VetManagerError:
        return client.fetch("Admission")


def _diagnosis_for(name: str) -> Any:
    """Диагноз из справочника: чего нет — заводим."""
    from medical.models import Diagnosis

    return _same_name(Diagnosis.objects.all(), name) or Diagnosis.objects.create(name=name[:150])


@transaction.atomic
def import_diagnoses(rows: list[dict[str, Any]] | None = None) -> StepResult:
    """Справочник диагнозов VetManager → наш справочник.

    В медкарте диагноз хранится номером из этого справочника, поэтому переносим его
    перед медкартами.
    """
    from medical.models import Diagnosis

    if rows is None:
        try:
            rows = client.fetch("MedicalCards/AllDiagnoses")
        except VetManagerError:
            rows = []
    result = StepResult("diagnoses", "Диагнозы", total=len(rows))
    for row in rows:
        name = _plain(_text(row, "title", "name"))[:150]
        external_id = str(row.get("id") or "")
        if not name or _link("diagnosis", external_id):
            result.skipped += 1 if name else 0
            continue
        found = _same_name(Diagnosis.objects.all(), name)
        if found is None:
            found = Diagnosis.objects.create(
                name=name,
                is_active=str(row.get("status", "ACTIVE")).upper() not in ("DELETED", "INACTIVE"),
            )
            result.created += 1
        else:
            result.updated += 1
        _remember("diagnosis", external_id, found.pk)
    return result


def _result_for(row: dict[str, Any], titles: dict[str, str]) -> Any:
    """Результат посещения: «выздоровление», «улучшение» — тоже из справочника VetManager."""
    from medical.models import VisitResult

    name = titles.get(str(row.get("meet_result_id") or ""), "")
    if not name:
        return None
    return _same_name(VisitResult.objects.all(), name) or VisitResult.objects.create(
        name=name[:100]
    )


def import_visits(
    rows: list[dict[str, Any]] | None = None, combo: list[dict[str, Any]] | None = None
) -> StepResult:
    """Медкарты VetManager → записи медкарты.

    Переносятся дата, питомец и владелец, врач, цель обращения, описание приёма,
    рекомендации, вес, температура, результат посещения и диагноз.
    Питомец должен быть перенесён заранее — без него запись не к кому привязать.
    """
    combo = _combo_items() if combo is None else combo
    if rows is None:
        with contextlib.suppress(VetManagerError):
            import_visit_purposes(combo)
            import_diagnoses()
        rows = _medical_rows()
    purposes = _combo_titles(combo, PURPOSE_MANUAL)
    results = _combo_titles(combo, RESULT_MANUAL)
    result = StepResult("visits", "Медкарты", total=len(rows))
    default_purpose = (
        _same_name(VisitPurpose.objects.all(), DEFAULT_PURPOSE) or VisitPurpose.objects.first()
    )
    if default_purpose is None:
        raise VetManagerError("Нет ни одной цели обращения — заполните справочник.")
    fallback_doctor: User | None = None
    # Порциями: медкарт тысячи, и обрыв посреди переноса не должен отменять уже сделанное.
    for batch_start in range(0, len(rows), VISITS_BATCH):
        with transaction.atomic():
            fallback_doctor = _import_visits_batch(
                rows[batch_start : batch_start + VISITS_BATCH],
                result,
                default_purpose,
                fallback_doctor,
                purposes,
                results,
            )
    return result


def _import_visits_batch(
    rows: list[dict[str, Any]],
    result: StepResult,
    default_purpose: VisitPurpose,
    fallback_doctor: User | None,
    purposes: dict[str, str],
    results: dict[str, str],
) -> User | None:
    """Одна порция медкарт — отдельной транзакцией (см. import_visits)."""
    from medical.models import VisitDiagnosis

    for row in rows:
        external_id = str(row.get("id") or "")
        if _link("visit", external_id):
            result.skipped += 1
            continue
        if str(row.get("status", "active")).lower() in ("deleted", "delete"):
            result.skipped += 1  # медкарту удалили в VetManager
            continue
        pet_link = _link("pet", str(row.get("patient_id") or ""))
        pet = (
            Pet.objects.filter(pk=pet_link.target_id).select_related("owner").first()
            if pet_link
            else None
        )
        if pet is None:
            result.errors.append(
                f"Медкарта {external_id}: питомец не перенесён — сначала перенесите питомцев."
            )
            continue
        # Дата и время приёма в VetManager — это date_edit (её правит врач),
        # date_create — когда запись завели.
        when = (
            _moment(row.get("date_edit"))
            or _moment(row.get("date_create"))
            or _moment(row.get("admission_date"))
        )
        if when is None:
            result.errors.append(f"Медкарта {external_id}: не разобрали дату.")
            continue
        doctor_link = _link("doctor", str(row.get("doctor_id") or row.get("user_id") or ""))
        doctor = User.objects.filter(pk=doctor_link.target_id).first() if doctor_link else None
        if doctor is None:
            fallback_doctor = fallback_doctor or _transfer_doctor()
            doctor = fallback_doctor
        visit = Visit.objects.create(
            pet=pet,
            client=pet.owner,
            doctor=doctor,
            date=when,
            purpose=_purpose_for(row, purposes, default_purpose),
            result=_result_for(row, results),
            weight=_positive(row.get("weight")),
            temperature=_positive(row.get("temperature")),
            treatment_html=clean(_text(row, "description")),
            recommendations_html=clean(_text(row, "recomendation", "recommendation")),
        )
        for diagnosis, kind in _diagnoses_of(row):
            VisitDiagnosis.objects.create(visit=visit, diagnosis=diagnosis, kind=kind)
        _remember("visit", external_id, visit.pk)
        result.created += 1
    return fallback_doctor


def _diagnosis_kinds_by_name(row: dict[str, Any]) -> dict[str, str]:
    """Вид каждого диагноза из подписи VetManager: «Пневмония (Предварительные)»."""
    from medical.models import VisitDiagnosis

    kinds: dict[str, str] = {}
    for part in re.findall(r"([^,;(]+)\(([^)]*)\)", _text(row, "diagnos_type_text")):
        name, kind_text = _plain(part[0]), simplify(part[1])
        if not name:
            continue
        kinds[name.lower()] = (
            VisitDiagnosis.Kind.FINAL if "окончат" in kind_text else VisitDiagnosis.Kind.PRELIMINARY
        )
    return kinds


def _diagnoses_of(row: dict[str, Any]) -> list[tuple[Any, str]]:
    """Диагнозы медкарты с их видом.

    В VetManager они приходят списком вида [{"id": 134, "type": 2}]: id — номер
    из справочника диагнозов. У старых записей бывает только текст.
    """
    from medical.models import Diagnosis, VisitDiagnosis

    kinds = _diagnosis_kinds_by_name(row)
    default_kind = VisitDiagnosis.Kind.PRELIMINARY
    found: list[tuple[Any, str]] = []
    raw = _text(row, "diagnos")
    numbers: list[str] = []
    if raw.startswith("["):
        with contextlib.suppress(ValueError):
            numbers = [
                str(item.get("id"))
                for item in json.loads(raw)
                if isinstance(item, dict) and item.get("id")
            ]
    elif raw.replace(",", "").replace(";", "").strip().isdigit():
        numbers = [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
    for number in numbers:
        if number == "0":
            continue
        link = _link("diagnosis", number)
        diagnosis = Diagnosis.objects.filter(pk=link.target_id).first() if link else None
        if diagnosis is not None:
            found.append((diagnosis, kinds.get(diagnosis.name.lower(), default_kind)))
    if found:
        return found
    text = _text(row, "diagnos_text")
    if not text or text.strip() in ("0", "-"):
        return []
    names = [_plain(part)[:150] for part in text.replace(";", ",").split(",") if _plain(part)]
    return [(_diagnosis_for(name), kinds.get(name.lower(), default_kind)) for name in names[:5]]


def _part_of_visit(model: Any, field_name: str) -> bool:
    """Части самой медкарты (диагнозы, назначения, профилактика) использованием не считаются:
    они удаляются вместе с ней."""
    return field_name == "visit" and model._meta.app_label == "medical"


@transaction.atomic
def reset_visits() -> int:
    """Убрать перенесённые медкарты, чтобы перенести их заново.

    Нужно, когда перенос улучшили: иначе уже перенесённые записи пропускаются и правки
    до них не доходят. Трогаем только перенесённые (по таблице соответствий) и только
    те, по которым ничего не завели у нас — счёт, стационар и прочее держат запись.
    """
    links = list(Imported.objects.filter(kind="visit"))
    removed = 0
    for link in links:
        visit = Visit.objects.filter(pk=link.target_id).first()
        if visit is not None:
            if core.usage_records(visit, skip=_part_of_visit):
                continue  # на запись уже ссылаются (счёт, стационар) — оставляем как есть
            visit.delete()
        link.delete()
        removed += 1
    return removed


def run_step(step: str, replace: bool = False) -> StepResult:
    """Выполнить шаг переноса: данные берутся из VetManager по его API."""
    if step == "units":
        return import_units()
    if step == "item_groups":
        return import_item_groups()
    if step == "items":
        return import_items()
    if step == "species":
        return import_species()
    if step == "clients":
        return import_clients()
    if step == "pets":
        return import_pets()
    if step == "doctors":
        return import_doctors()
    if step == "diagnoses":
        return import_diagnoses()
    if step == "visits":
        if replace:
            reset_visits()
        return import_visits()
    raise VetManagerError(f"Неизвестный шаг переноса: {step}.")


def status() -> list[dict[str, Any]]:
    """Что уже перенесено — для экрана переноса.

    У шага может быть несколько видов записей (виды животных и породы) — считаем все
    и показываем подробно, чтобы не выглядело, будто породы не перенеслись.
    """
    kinds: dict[str, list[tuple[str, str]]] = {
        "units": [("unit", "единиц")],
        "item_groups": [("item_group", "групп")],
        "items": [("item", "позиций")],
        "species": [("species", "видов"), ("breed", "пород")],
        "clients": [("client", "клиентов")],
        "pets": [("pet", "питомцев")],
        "doctors": [("doctor", "врачей")],
        "diagnoses": [("diagnosis", "диагнозов")],
        "visits": [("visit", "приёмов")],
    }
    rows = []
    for step, title in STEPS:
        counts = [(imported_count(kind), label) for kind, label in kinds[step]]
        total = sum(count for count, _ in counts)
        detail = ", ".join(f"{count} {label}" for count, label in counts if count)
        rows.append(
            {
                "step": step,
                "title": title,
                "imported": total,
                "detail": detail if len(counts) > 1 else "",
            }
        )
    return rows
