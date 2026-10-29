"""API договоров клиента."""

from typing import Any

from django.db.models import QuerySet
from django.utils import timezone
from rest_framework import serializers, viewsets

from clients import services
from clients.models import ClientContract


class ContractSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    is_active = serializers.SerializerMethodField()
    attachment_name = serializers.CharField(source="attachment.name", read_only=True, default="")

    class Meta:
        model = ClientContract
        fields = [
            "id", "client", "number", "date", "valid_until", "attachment", "attachment_name",
            "comment", "is_active", "created_at",
        ]  # fmt: skip
        extra_kwargs = {"number": {"required": False, "allow_blank": True}}

    def get_is_active(self, contract: ClientContract) -> bool:
        return contract.valid_until is None or contract.valid_until >= timezone.localdate()

    def _save(self, contract: ClientContract, data: dict[str, Any]) -> ClientContract:
        for field, value in data.items():
            setattr(contract, field, value)
        try:
            return services.save_contract(contract)
        except services.ClientError as error:
            raise serializers.ValidationError({"non_field_errors": [str(error)]}) from error

    def create(self, validated_data: dict[str, Any]) -> ClientContract:
        return self._save(ClientContract(number=""), validated_data)

    def update(self, instance: ClientContract, validated_data: dict[str, Any]) -> ClientContract:
        validated_data.pop("client", None)
        return self._save(instance, validated_data)


class ContractViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]
    """Договоры. Фильтр ?client=<id>."""

    serializer_class = ContractSerializer
    queryset = ClientContract.objects.all()

    def get_queryset(self) -> QuerySet[ClientContract]:
        queryset = ClientContract.objects.select_related("attachment")
        if client := self.request.query_params.get("client"):
            queryset = queryset.filter(client=client)
        return queryset
