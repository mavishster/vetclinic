"""API клиентов: карточка с телефонами, список с поиском и фильтрами, поиск дублей."""

from typing import Any

from django.db.models import QuerySet
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from clients import services
from clients.models import Client, ClientPhone, Pet


class PhoneSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    class Meta:
        model = ClientPhone
        fields = ["kind", "number", "is_primary", "comment"]


class ClientSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    phones = PhoneSerializer(many=True, required=False)
    full_name = serializers.CharField(read_only=True)
    city_name = serializers.CharField(source="city.name", read_only=True, default="")
    street_name = serializers.CharField(source="street.name", read_only=True, default="")
    client_type_name = serializers.CharField(source="client_type.name", read_only=True, default="")
    source_name = serializers.CharField(source="source.name", read_only=True, default="")
    pet_names = serializers.SerializerMethodField()
    has_contract = serializers.SerializerMethodField()
    contract_number = serializers.SerializerMethodField()
    contract_expired = serializers.SerializerMethodField()
    address = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()
    last_invoice_at = serializers.SerializerMethodField()
    photo = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = [
            "id", "number", "full_name", "last_name", "first_name", "middle_name", "passport",
            "city", "city_name", "street", "street_name", "house", "zip_code", "email",
            "discount_percent", "journal_number", "discount_card",
            "client_type", "client_type_name", "source", "source_name",
            "no_mailing", "in_blacklist", "description", "status", "phones", "pet_names",
            "has_contract", "contract_number", "contract_expired",
            "address", "balance", "last_invoice_at", "photo", "photo_consent_at",
            "created_at", "updated_at",
        ]  # fmt: skip
        read_only_fields = ["photo", "photo_consent_at"]

    def get_photo(self, client: Client) -> str | None:
        """Фото — только если его файл не удалён из «Файлов» клиента."""
        photo = client.photo
        return str(photo.pk) if photo is not None and not photo.is_deleted else None

    def get_has_contract(self, client: Client) -> bool:
        flag = getattr(client, "has_contract", None)  # в списке — посчитан одним запросом
        return services.has_active_contract(client) if flag is None else bool(flag)

    def get_contract_number(self, client: Client) -> str:
        return services.contract_summary(client)[0]

    def get_contract_expired(self, client: Client) -> bool:
        return services.contract_summary(client)[1]

    def get_address(self, client: Client) -> str:
        return services.address_line(client)

    def get_balance(self, client: Client) -> str:
        value = getattr(client, "balance_value", None)  # в списке — посчитан одним запросом
        return str(services.balance(client) if value is None else value)

    def get_last_invoice_at(self, client: Client) -> Any:
        if hasattr(client, "last_invoice_value"):
            return client.last_invoice_value
        return services.last_invoice_at(client)

    def get_pet_names(self, client: Client) -> list[str]:
        return [pet.name for pet in client.pets.all() if pet.status == Pet.Status.ACTIVE]

    def _save(self, client: Client, data: dict[str, Any]) -> Client:
        phones = data.pop("phones", None)
        for field, value in data.items():
            setattr(client, field, value)
        try:
            return services.save_client(client, phones)
        except services.ClientError as error:
            raise serializers.ValidationError({"non_field_errors": [str(error)]}) from error

    def create(self, validated_data: dict[str, Any]) -> Client:
        return self._save(Client(), validated_data)

    def update(self, instance: Client, validated_data: dict[str, Any]) -> Client:
        return self._save(instance, validated_data)


class ClientPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class ClientViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]
    """Клиенты.

    Фильтры: ?search=текст (ФИО, телефон, номер по журналу, дисконтная карта),
    ?status=active,temporary, ?city=, ?client_type=, ?blacklist=true, ?contract=yes|no.
    """

    serializer_class = ClientSerializer
    pagination_class = ClientPagination
    queryset = Client.objects.all()

    def get_queryset(self) -> QuerySet[Client]:
        queryset = services.with_balance_columns(
            services.with_contract_flag(
                Client.objects.select_related("city", "street", "client_type", "source")
            )
        ).prefetch_related("phones", "pets")
        params = self.request.query_params
        if search := params.get("search", "").strip():
            queryset = services.search_clients(queryset, search)
        if status := params.get("status"):
            queryset = queryset.filter(status__in=status.split(","))
        for field in ("city", "client_type"):
            if value := params.get(field):
                queryset = queryset.filter(**{field: value})
        if params.get("blacklist", "").lower() in {"1", "true"}:
            queryset = queryset.filter(in_blacklist=True)
        if (contract := params.get("contract")) in {"yes", "no"}:
            queryset = queryset.filter(has_contract=contract == "yes")
        return queryset

    @action(detail=True, methods=["post"], parser_classes=[MultiPartParser])
    def photo(self, request: Request, pk: str | None = None) -> Response:
        """Фото владельца с камеры (multipart: file). Только с согласием клиента."""
        client = self.get_object()
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": ["Нет снимка."]})
        try:
            services.save_photo(client, upload)
        except services.ClientError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error
        return Response(self.get_serializer(client).data)

    @action(detail=False, methods=["get"])
    def duplicates(self, request: Request) -> Response:
        """Возможные дубли: ?last_name=&first_name=&middle_name=&phone=…&phone=…&exclude=id"""
        params = request.query_params
        return Response(
            services.find_duplicates(
                last_name=params.get("last_name", ""),
                first_name=params.get("first_name", ""),
                middle_name=params.get("middle_name", ""),
                phones=params.getlist("phone"),
                exclude_id=params.get("exclude") or None,
            )
        )
