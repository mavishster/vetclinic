"""Клиенты и питомцы: публичный вход модуля.

Отвечает за: клиентов, питомцев, смену владельца, договоры, поиск дублей, баланс клиента.

Другие модули обращаются к модулю только через функции этого файла.
Бизнес-правила живут здесь, а не в моделях и не в API (ENGINEERING.md).
"""

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, TypedDict

from django.contrib.postgres.search import TrigramSimilarity
from django.db import transaction
from django.db.models import Exists, OuterRef, Q, QuerySet, Value
from django.db.models.functions import Concat
from django.utils import timezone

from clients.models import (
    Client,
    ClientContract,
    ClientPhone,
    Pet,
    PetOwnership,
    PetWeight,
    phone_search_key,
)
from core import services as core_services

# Насколько похожими должны быть ФИО, чтобы считаться возможным дублем (0…1).
NAME_SIMILARITY = 0.5


class ClientError(Exception):
    """Ошибка в данных клиента. Текст — для пользователя."""


# --- Телефоны ----------------------------------------------------------------------


def validate_phone(number: str) -> str:
    number = number.strip()
    digits = re.sub(r"\D", "", number)
    if not 5 <= len(digits) <= 15:
        raise ClientError(f"Проверьте номер телефона: «{number}».")
    return number


class PhoneData(TypedDict, total=False):
    kind: str
    number: str
    is_primary: bool
    comment: str


def _replace_phones(client: Client, phones: list[PhoneData]) -> None:
    """Заменить телефоны клиента. Основной — отмеченный, иначе первый."""
    client.phones.all().delete()
    if phones and not any(p.get("is_primary") for p in phones):
        phones = [{**phones[0], "is_primary": True}, *phones[1:]]
    seen_primary = False
    for phone in phones:
        number = validate_phone(phone["number"])
        is_primary = bool(phone.get("is_primary")) and not seen_primary
        seen_primary = seen_primary or is_primary
        ClientPhone.objects.create(
            client=client,
            kind=phone.get("kind") or ClientPhone.Kind.MOBILE,
            number=number,
            is_primary=is_primary,
            comment=phone.get("comment", ""),
        )


# --- Карточка клиента --------------------------------------------------------------


@transaction.atomic
def save_client(client: Client, phones: list[PhoneData] | None = None) -> Client:
    """Сохранить карточку клиента вместе с телефонами (если переданы)."""
    client.last_name = client.last_name.strip()
    if not client.last_name:
        raise ClientError("Укажите фамилию.")
    if client.street is not None and client.street.city_id != client.city_id:
        raise ClientError("Улица не относится к выбранному городу.")
    client.save()
    if phones is not None:
        _replace_phones(client, phones)
    return client


def set_status(client: Client, status: str) -> Client:
    """Активировать, деактивировать или сделать временным клиента."""
    if status not in Client.Status.values:
        raise ClientError(f"Неизвестный статус: {status}")
    client.status = status
    client.save(update_fields=["status"])
    return client


# --- Поиск -------------------------------------------------------------------------


def search_clients(queryset: QuerySet[Client], text: str) -> QuerySet[Client]:
    """Быстрый поиск: каждое слово ищется в ФИО и кличках питомцев; цифры — ещё и в
    телефонах, номере по журналу и дисконтной карте. «иван 345» найдёт Иванова с телефоном …345…"""
    for word in text.split():
        condition = (
            Q(last_name__icontains=word)
            | Q(first_name__icontains=word)
            | Q(middle_name__icontains=word)
            | Q(journal_number__iexact=word)
            | Q(discount_card__iexact=word)
            | Q(pets__name__icontains=word)
        )
        digits = re.sub(r"\D", "", word)
        if len(digits) >= 3:
            condition |= Q(phones__search_key__contains=digits[-10:])
        queryset = queryset.filter(condition)
    return queryset.distinct()


class Duplicate(TypedDict):
    id: str
    full_name: str
    phones: list[str]
    city: str
    status: str
    reasons: list[str]  # "phone" — совпал телефон, "name" — похожее ФИО


def find_duplicates(
    last_name: str = "",
    first_name: str = "",
    middle_name: str = "",
    phones: list[str] | None = None,
    exclude_id: Any = None,
    limit: int = 10,
) -> list[Duplicate]:
    """Возможные дубли клиента: совпадающий телефон или похожее ФИО.

    Показываются и неактивные клиенты — их лучше восстановить, чем завести заново.
    """
    reasons: dict[Any, set[str]] = {}

    keys = [key for key in (phone_search_key(p) for p in phones or []) if len(key) >= 5]
    if keys:
        by_phone = Client.objects.filter(phones__search_key__in=keys).values_list("pk", flat=True)
        for pk in by_phone:
            reasons.setdefault(pk, set()).add("phone")

    full_name = " ".join(p.strip() for p in (last_name, first_name, middle_name) if p.strip())
    if len(last_name.strip()) >= 2:
        db_name = Concat("last_name", Value(" "), "first_name", Value(" "), "middle_name")
        similar = (
            Client.objects.annotate(similarity=TrigramSimilarity(db_name, full_name))
            .filter(similarity__gte=NAME_SIMILARITY)
            .order_by("-similarity")
            .values_list("pk", flat=True)[: limit * 2]
        )
        for pk in similar:
            reasons.setdefault(pk, set()).add("name")

    reasons.pop(exclude_id, None)
    if exclude_id is not None:
        reasons = {pk: r for pk, r in reasons.items() if str(pk) != str(exclude_id)}
    clients = (
        Client.objects.filter(pk__in=reasons).select_related("city").prefetch_related("phones")
    )
    found: list[Duplicate] = [
        {
            "id": str(client.pk),
            "full_name": client.full_name,
            "phones": [phone.number for phone in client.phones.all()],
            "city": client.city.name if client.city else "",
            "status": client.status,
            "reasons": sorted(reasons[client.pk]),
        }
        for client in clients
    ]
    # Сначала совпавшие по телефону — это почти наверняка тот же человек.
    found.sort(key=lambda d: ("phone" not in d["reasons"], d["full_name"]))
    return found[:limit]


# --- Питомцы -----------------------------------------------------------------------


def _today() -> date:
    return timezone.localdate()


@transaction.atomic
def save_pet(pet: Pet) -> Pet:
    """Сохранить карточку питомца. Новому питомцу открывается период владения."""
    pet.name = pet.name.strip()
    if not pet.name:
        raise ClientError("Укажите кличку.")
    if pet.breed.species_id != pet.species_id:
        raise ClientError("Порода не относится к выбранному виду.")
    if pet.birth_date and pet.birth_date > _today():
        raise ClientError("Дата рождения не может быть в будущем.")
    if pet.status == Pet.Status.DEAD:
        if pet.death_date is None:
            pet.death_date = _today()
        if pet.birth_date and pet.death_date < pet.birth_date:
            raise ClientError("Дата смерти раньше даты рождения.")
    else:
        pet.death_date = None
    is_new = pet._state.adding
    pet.save()
    if is_new:
        PetOwnership.objects.create(pet=pet, client=pet.owner, date_from=_today())
    return pet


@transaction.atomic
def transfer_pet(pet: Pet, new_owner: Client) -> Pet:
    """Передать питомца другому владельцу.

    Медкарта уходит вместе с питомцем, а счета остаются у прежнего владельца.
    У прежнего владельца питомец виден в «бывших».
    """
    if new_owner.pk == pet.owner_id:
        raise ClientError("Питомец уже принадлежит этому клиенту.")
    today = _today()
    pet.ownerships.filter(date_to__isnull=True).update(date_to=today)
    PetOwnership.objects.create(pet=pet, client=new_owner, date_from=today)
    pet.owner = new_owner
    pet.save(update_fields=["owner"])
    return pet


def mark_dead(pet: Pet, death_date: date | None = None) -> Pet:
    """Отметить, что питомец умер: он исчезает из напоминаний и рассылок."""
    pet.status = Pet.Status.DEAD
    pet.death_date = death_date or _today()
    return save_pet(pet)


def add_weight(pet: Pet, weight: Decimal, on: date | None = None) -> PetWeight:
    if weight <= 0 or weight > 2000:
        raise ClientError("Проверьте вес: он должен быть больше нуля и в килограммах.")
    on = on or _today()
    if on > _today():
        raise ClientError("Дата взвешивания не может быть в будущем.")
    return PetWeight.objects.create(pet=pet, weight=weight, date=on)


def current_weight(pet: Pet) -> PetWeight | None:
    return pet.weights.first()


def former_pets(client: Client) -> QuerySet[Pet]:
    """Питомцы, которых клиент передал другим владельцам."""
    return (
        Pet.objects.filter(ownerships__client=client, ownerships__date_to__isnull=False)
        .exclude(owner=client)
        .distinct()
    )


def search_pets(queryset: QuerySet[Pet], text: str) -> QuerySet[Pet]:
    """Поиск питомцев: кличка, № чипа, лабораторный №, фамилия владельца."""
    for word in text.split():
        queryset = queryset.filter(
            Q(name__icontains=word)
            | Q(chip_number__icontains=word)
            | Q(lab_number__iexact=word)
            | Q(owner__last_name__icontains=word)
        )
    return queryset.distinct()


def current_owner(pet: Pet) -> Client:
    """Текущий владелец питомца — для других модулей (счета, медкарта)."""
    return pet.owner


# --- Договоры ----------------------------------------------------------------------


def save_contract(contract: ClientContract) -> ClientContract:
    """Сохранить договор. Номер не указан — выдаётся автоматически («K1-000001»)."""
    contract.number = contract.number.strip() or core_services.next_number("contract")
    contract.date = contract.date or _today()
    if contract.valid_until and contract.valid_until < contract.date:
        raise ClientError("Срок действия договора раньше его даты.")
    if contract.attachment and (
        contract.attachment.owner_id != contract.client_id
        or contract.attachment.owner_type.model != "client"
    ):
        raise ClientError("Скан договора должен быть прикреплён к этому же клиенту.")
    contract.save()
    return contract


def active_contracts() -> QuerySet[ClientContract]:
    today = _today()
    return ClientContract.objects.filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))


def has_active_contract(client: Client) -> bool:
    return active_contracts().filter(client=client).exists()


def with_contract_flag(queryset: QuerySet[Client]) -> QuerySet[Client]:
    """Добавить к клиентам признак has_contract — есть действующий договор."""
    return queryset.annotate(has_contract=Exists(active_contracts().filter(client=OuterRef("pk"))))


def set_weight_on(pet: Pet, on: date, weight: Decimal) -> PetWeight:
    """Вес на дату (с приёма): одно взвешивание в день — повторное сохранение его обновляет."""
    if weight <= 0 or weight > 2000:
        raise ClientError("Проверьте вес: он должен быть больше нуля и в килограммах.")
    record = pet.weights.filter(date=on).first()
    if record is None:
        return PetWeight.objects.create(pet=pet, weight=weight, date=on)
    record.weight = weight
    record.save(update_fields=["weight"])
    return record


def mark_sterilized(pet: Pet) -> None:
    """Стерилизация / кастрация проведена — отметка в карточке питомца."""
    if not pet.sterilized:
        pet.sterilized = True
        pet.save(update_fields=["sterilized"])


def set_chip_number(pet: Pet, number: str) -> None:
    """Чипирование — номер чипа в карточку питомца."""
    pet.chip_number = number.strip()
    pet.save(update_fields=["chip_number"])


# --- Баланс клиента ----------------------------------------------------------------


def charge(client: Any, amount: Decimal, source: Any) -> None:
    """Начислить клиенту сумму документа (выполненный счёт) — долг растёт."""
    from clients.models import ClientLedger

    core_services.post_entry(
        ClientLedger, source, client_id=getattr(client, "pk", client), amount=amount
    )


def reverse_charges(source: Any) -> None:
    """Снять начисления документа (откат счёта)."""
    from clients.models import ClientLedger

    core_services.reverse_entries(ClientLedger, source)


def balance(client: Any) -> Decimal:
    """Баланс клиента: > 0 — аванс, < 0 — долг."""
    from django.db.models import Sum

    from clients.models import ClientLedger

    total = ClientLedger.objects.filter(client=client).aggregate(total=Sum("amount"))["total"]
    return -(total or Decimal("0"))


def pay(client: Any, amount: Decimal, source: Any) -> None:
    """Оплата или аванс от клиента — баланс уменьшается (долг гасится, растёт аванс)."""
    charge(client, -amount, source)


def current_owner_id(pet_id: Any) -> Any:
    return Pet.objects.filter(pk=pet_id).values_list("owner_id", flat=True).first()


def guest_client() -> Client:
    """Служебный клиент «Гость» для быстрых счетов: создаётся при первом обращении."""
    guest = Client.objects.filter(is_guest=True).first()
    if guest is None:
        guest = Client(
            last_name="Гость", is_guest=True, description="Служебный клиент для быстрых счетов"
        )
        guest.save()
    return guest


def is_guest(client: Any) -> bool:
    return Client.objects.filter(pk=getattr(client, "pk", client), is_guest=True).exists()


def pet_by_lab_number(code: str) -> Pet | None:
    """Питомец по лабораторному номеру из карточки — для результатов анализов."""
    code = (code or "").strip()
    return Pet.objects.filter(lab_number=code).first() if code else None


# --- Подпись на планшете -----------------------------------------------------------

SIGN_WAIT_MINUTES = 15


class SigningError(Exception):
    """Подписание невозможно. Текст — для пользователя."""


def client_print_context(client: Client, contract: Any = None) -> dict[str, Any]:
    """Данные клиента для документа на подпись: ФИО, телефоны, адрес, питомцы, договор."""
    return {
        "client": {
            "full_name": client.full_name,
            "phones": ", ".join(p.number for p in client.phones.all()),
            "address": ", ".join(
                part
                for part in (
                    f"г. {client.city.name}" if client.city else "",
                    client.street.name if client.street else "",
                    client.house,
                )
                if part
            ),
            "email": client.email,
        },
        "pets": [
            {"name": p.name, "species": p.species.name, "breed": p.breed.name}
            for p in Pet.objects.filter(owner=client, status=Pet.Status.ACTIVE).select_related(
                "species", "breed"
            )
        ],
        "contract": {"number": contract.number, "date": contract.date} if contract else {},
    }


def sample_client_document_context() -> dict[str, Any]:
    return {
        "client": {
            "full_name": "Иванова Анна Петровна",
            "phones": "+7 900 111-22-33",
            "address": "г. Москва, ул. Лесная, д. 5",
            "email": "anna@example.ru",
        },
        "pets": [{"name": "Барсик", "species": "Кошки", "breed": "Метис"}],
        "contract": {"number": "К-15", "date": timezone.localdate()},
    }


def station_of(user: Any) -> Any:
    from clients.models import SigningStation

    return SigningStation.objects.filter(user=user, is_active=True).first()


@transaction.atomic
def send_for_signature(
    client: Client,
    template: Any,
    station: Any,
    user: Any,
    purpose: str = "other",
    contract: Any = None,
) -> Any:
    """Отправить документ на планшет. Текст фиксируется сейчас (с контрольной суммой).

    На планшете одновременно — один документ: прежний, если не подписан, отменяется.
    """
    import hashlib

    from clients.models import SignatureRequest
    from core import printing
    from core import services as core_services

    if contract is not None and contract.client_id != client.pk:
        raise SigningError("Договор другого клиента.")
    html = printing.render_html(
        template.body,
        {**core_services.common_print_context(user), **client_print_context(client, contract)},
    )
    SignatureRequest.objects.filter(station=station, status=SignatureRequest.Status.PENDING).update(
        status=SignatureRequest.Status.CANCELLED
    )
    from clients.models import PhotoRequest

    PhotoRequest.objects.filter(station=station, status=PhotoRequest.Status.PENDING).update(
        status=PhotoRequest.Status.CANCELLED
    )
    return SignatureRequest.objects.create(
        client=client,
        station=station,
        title=template.name,
        purpose=purpose,
        contract=contract,
        html=html,
        content_hash=hashlib.sha256(html.encode("utf-8")).hexdigest(),
        sent_by=user,
        expires_at=timezone.now() + timedelta(minutes=SIGN_WAIT_MINUTES),
    )


def pending_for(station: Any) -> Any:
    """Документ, ждущий подписи на этом планшете (не отменён и не просрочен)."""
    from clients.models import SignatureRequest

    return (
        SignatureRequest.objects.filter(
            station=station, status=SignatureRequest.Status.PENDING, expires_at__gt=timezone.now()
        )
        .select_related("client")
        .first()
    )


def cancel_signature(request: Any) -> None:
    from clients.models import SignatureRequest

    if request.status == SignatureRequest.Status.PENDING:
        request.status = SignatureRequest.Status.CANCELLED
        request.save(update_fields=["status"])


def _signature_png(data_url: str) -> bytes:
    import base64
    import io

    from PIL import Image

    prefix = "data:image/png;base64,"
    if not data_url.startswith(prefix):
        raise SigningError("Подпись не получена.")
    try:
        raw = base64.b64decode(data_url[len(prefix) :], validate=True)
        image = Image.open(io.BytesIO(raw))
        image.verify()
    except Exception as error:  # noqa: BLE001 — любой мусор = понятное сообщение
        raise SigningError("Подпись не получена — попробуйте ещё раз.") from error
    if len(raw) > 2 * 1024 * 1024 or image.size[0] > 4000 or image.size[1] > 4000:
        raise SigningError("Слишком большое изображение подписи.")
    return raw


@transaction.atomic
def sign(request: Any, station: Any, signature_data_url: str, signed_from: str = "") -> Any:
    """Принять подпись: собрать PDF (документ + подпись + сведения о подписании),
    положить в файлы клиента; договор — отметить подписанным, согласие — записать в карточку."""
    import base64
    from html import escape

    from django.core.files.base import ContentFile

    from clients.models import SignatureRequest
    from core import printing
    from core.attachments import attach
    from core.models import FileCategory

    request = SignatureRequest.objects.select_for_update().get(pk=request.pk)
    if request.station_id != station.pk:
        raise SigningError("Этот документ отправлен на другой планшет.")
    if request.status != SignatureRequest.Status.PENDING:
        raise SigningError("Документ уже подписан или отменён.")
    if request.expires_at <= timezone.now():
        raise SigningError("Время ожидания подписи истекло — попросите отправить документ снова.")
    png = _signature_png(signature_data_url)
    now = timezone.now()
    info = (
        '<div style="margin-top:18px; page-break-inside:avoid;">'
        "<p><b>Подпись клиента:</b><br>"
        f'<img src="data:image/png;base64,{base64.b64encode(png).decode()}" '
        'style="height:30mm; border-bottom:1px solid #333;"></p>'
        '<p style="font-size:8pt; color:#555;">Подписано на планшете «'
        f"{escape(station.name)}» {timezone.localtime(now):%d.%m.%Y %H:%M}. "
        f"Отправил на подпись: {escape(request.sent_by.short_name or request.sent_by.username)}. "
        f"Контрольная сумма текста (SHA-256): {request.content_hash}.</p></div>"
    )
    html = (
        request.html.replace("</body>", f"{info}</body>")
        if "</body>" in request.html
        else request.html + info
    )
    pdf = printing.html_to_pdf(html)
    category = FileCategory.objects.filter(
        name="Договор" if request.purpose == "contract" else "Общий"
    ).first()
    stamp = timezone.localtime(now).strftime("%Y-%m-%d")
    attachment = attach(
        "clients.client",
        request.client_id,
        ContentFile(pdf, name=f"{request.title} ({stamp}).pdf"),
        name=f"{request.title} — подписан {timezone.localtime(now):%d.%m.%Y %H:%M}",
        category=category,
    )
    attachment.content_type = "application/pdf"
    attachment.save(update_fields=["content_type"])
    request.status = SignatureRequest.Status.SIGNED
    request.signed_at = now
    request.signed_from = signed_from[:255]
    request.result = attachment
    request.save()
    if request.contract_id:
        request.contract.attachment = attachment
        request.contract.save(update_fields=["attachment"])
    elif request.purpose == SignatureRequest.Purpose.CONTRACT:
        # Договор подписали без заранее заведённого договора — заводим его сами:
        # номер — следующий по порядку, дата — сегодня, скан — подписанный PDF.
        request.contract = save_contract(
            ClientContract(
                client_id=request.client_id,
                number="",
                date=timezone.localdate(now),
                attachment=attachment,
            )
        )
        request.save(update_fields=["contract"])
    if request.purpose == SignatureRequest.Purpose.CONSENT:
        Client.objects.filter(pk=request.client_id).update(photo_consent_at=now)
    return request


# --- Фото клиента ------------------------------------------------------------------

PHOTO_MAX_PX = 800


def save_photo(client: Client, file: Any) -> Any:
    """Фото владельца с камеры: уменьшается до 800 px, хранится как файл клиента («Фото»)."""
    import io

    from django.core.files.base import ContentFile
    from PIL import Image, ImageOps

    from core.attachments import attach
    from core.models import FileCategory

    if client.photo_consent_at is None:
        raise ClientError("Нет согласия клиента на фотографирование — сначала подпишите согласие.")
    try:
        image = ImageOps.exif_transpose(Image.open(file)).convert("RGB")
    except Exception as error:  # noqa: BLE001
        raise ClientError("Не удалось прочитать снимок.") from error
    image.thumbnail((PHOTO_MAX_PX, PHOTO_MAX_PX))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=85)
    stamp = timezone.localtime().strftime("%Y-%m-%d")
    attachment = attach(
        "clients.client",
        client.pk,
        ContentFile(buffer.getvalue(), name=f"Фото {stamp}.jpg"),
        name=f"Фото владельца {timezone.localtime():%d.%m.%Y}",
        category=FileCategory.objects.filter(name="Фото").first(),
    )
    attachment.content_type = "image/jpeg"
    attachment.save(update_fields=["content_type"])
    client.photo = attachment
    client.save(update_fields=["photo"])
    return attachment


# --- Фото камерой планшета ---------------------------------------------------------


@transaction.atomic
def request_photo(client: Client, station: Any, user: Any) -> Any:
    """Попросить планшет сделать снимок клиента. Только с согласием клиента.

    На планшете одно задание за раз: прежние неподписанные документы и снимки отменяются.
    """
    from clients.models import PhotoRequest, SignatureRequest

    if client.photo_consent_at is None:
        raise ClientError("Нет согласия клиента на фотографирование — сначала подпишите согласие.")
    PhotoRequest.objects.filter(station=station, status=PhotoRequest.Status.PENDING).update(
        status=PhotoRequest.Status.CANCELLED
    )
    SignatureRequest.objects.filter(station=station, status=SignatureRequest.Status.PENDING).update(
        status=SignatureRequest.Status.CANCELLED
    )
    return PhotoRequest.objects.create(
        client=client,
        station=station,
        sent_by=user,
        expires_at=timezone.now() + timedelta(minutes=SIGN_WAIT_MINUTES),
    )


def pending_photo_for(station: Any) -> Any:
    from clients.models import PhotoRequest

    return (
        PhotoRequest.objects.filter(
            station=station, status=PhotoRequest.Status.PENDING, expires_at__gt=timezone.now()
        )
        .select_related("client")
        .first()
    )


@transaction.atomic
def take_photo_on_station(request: Any, station: Any, file: Any) -> Any:
    """Снимок с планшета: проверки — как у подписи, сохранение — как у фото с компьютера."""
    from clients.models import PhotoRequest

    request = PhotoRequest.objects.select_for_update().select_related("client").get(pk=request.pk)
    if request.station_id != station.pk:
        raise SigningError("Этот снимок запрошен на другом планшете.")
    if request.status != PhotoRequest.Status.PENDING:
        raise SigningError("Снимок уже сделан или отменён.")
    if request.expires_at <= timezone.now():
        raise SigningError("Время ожидания истекло — попросите запросить снимок снова.")
    try:
        attachment = save_photo(request.client, file)
    except ClientError as error:
        raise SigningError(str(error)) from error
    request.status = PhotoRequest.Status.DONE
    request.result = attachment
    request.save()
    return request


def cancel_photo(request: Any) -> None:
    from clients.models import PhotoRequest

    if request.status == PhotoRequest.Status.PENDING:
        request.status = PhotoRequest.Status.CANCELLED
        request.save(update_fields=["status"])
