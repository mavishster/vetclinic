"""Перенос из VetManager: публичный вход модуля.

Отвечает за: перенос справочников, товаров и услуг, клиентов, питомцев, медкарт и счетов.
Переносим по шагам и повторяемо: уже перенесённое не задваивается (таблица Imported).

Бизнес-правила живут здесь, а не в моделях и не в API (ENGINEERING.md).
"""

import contextlib
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction

from catalog import services as catalog
from catalog.models import Item, ItemGroup, ItemUnit, Kind, Unit
from clients import services as clients_services
from clients.models import Breed, City, Client, Pet, Species
from vetmanager import client
from vetmanager.models import Imported

VetManagerError = client.VetManagerError

# Шаги переноса — по порядку: каждый следующий опирается на предыдущие.
STEPS = [
    ("units", "Единицы измерения"),
    ("item_groups", "Группы прайса"),
    ("items", "Товары и услуги"),
    ("species", "Виды и породы"),
    ("clients", "Клиенты"),
    ("pets", "Питомцы"),
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

_SEX = {
    "мальчик": Pet.Sex.MALE,
    "male": Pet.Sex.MALE,
    "м": Pet.Sex.MALE,
    "девочка": Pet.Sex.FEMALE,
    "female": Pet.Sex.FEMALE,
    "ж": Pet.Sex.FEMALE,
}


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


def _phones(row: dict[str, Any]) -> list[clients_services.PhoneData]:
    """Телефоны клиента: мобильный — основной, домашний и рабочий — следом."""
    prefix = _text(row, "phone_prefix")
    found: list[clients_services.PhoneData] = []
    for source, kind in (("cell_phone", "mobile"), ("home_phone", "home"), ("work_phone", "work")):
        number = _text(row, source)
        if not number:
            continue
        if prefix and not number.startswith(("+", prefix)):
            number = f"{prefix}{number}"
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
    for row in rows:
        external_id = str(row.get("id") or "")
        last_name = _text(row, "last_name")
        if not last_name:
            last_name = (
                _text(row, "first_name") or _text(row, "cell_phone") or f"Без имени {external_id}"
            )
        if _link("client", external_id):
            result.skipped += 1
            continue
        city_name = _text(row, "city")
        city = None
        if city_name:
            city = _same_name(City.objects.all(), city_name) or City.objects.create(
                name=city_name[:100]
            )
        house = " ".join(part for part in (_text(row, "address"), _text(row, "apartment")) if part)
        status = Client.Status.ACTIVE
        if str(row.get("status", "")).upper() in ("DELETED", "INACTIVE", "ARCHIVE"):
            status = Client.Status.INACTIVE
        record = Client(
            last_name=last_name[:100],
            first_name=_text(row, "first_name")[:100],
            middle_name=_text(row, "middle_name")[:100],
            passport=_text(row, "passport_series")[:50],
            city=city,
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
            saved = clients_services.save_client(record, _phones(row))
        except clients_services.ClientError as error:
            result.errors.append(f"«{last_name}»: {error}")
            continue
        _remember("client", external_id, saved.pk)
        result.created += 1
    return result


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
        if _link("pet", external_id):
            result.skipped += 1
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
        pet = Pet(
            owner=owner,
            name=name,
            species=species,
            breed=breed,
            sex=_SEX.get(_text(row, "sex").lower(), Pet.Sex.UNKNOWN),
            birth_date=_date(row.get("birthday")),
            chip_number=_text(row, "chip_number")[:50],
            lab_number=_text(row, "lab_number")[:50],
            notes=" ".join(part for part in (_text(row, "note"), _text(row, "deathnote")) if part),
            status=Pet.Status.DEAD if death else Pet.Status.ACTIVE,
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
        result.created += 1
    return result


def run_step(step: str) -> StepResult:
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
