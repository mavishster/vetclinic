"""API питомцев: карточка, список, передача владельцу, отметка о смерти, вес."""

from typing import Any

from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from clients import services
from clients.api.clients import ClientPagination
from clients.models import Client, Pet, PetWeight


class PetSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    owner_name = serializers.CharField(source="owner.full_name", read_only=True)
    species_name = serializers.CharField(source="species.name", read_only=True)
    breed_name = serializers.CharField(source="breed.name", read_only=True)
    color_name = serializers.CharField(source="color.name", read_only=True, default="")
    weight = serializers.SerializerMethodField()

    class Meta:
        model = Pet
        fields = [
            "id", "owner", "owner_name", "name", "species", "species_name", "breed", "breed_name",
            "sex", "sterilized", "color", "color_name", "birth_date", "birth_date_approximate",
            "chip_number", "lab_number", "notes", "status", "death_date", "weight",
            "created_at", "updated_at",
        ]  # fmt: skip

    def get_weight(self, pet: Pet) -> dict[str, Any] | None:
        latest = services.current_weight(pet)
        return {"weight": str(latest.weight), "date": latest.date} if latest else None

    def _save(self, pet: Pet, data: dict[str, Any]) -> Pet:
        for field, value in data.items():
            setattr(pet, field, value)
        try:
            return services.save_pet(pet)
        except services.ClientError as error:
            raise serializers.ValidationError({"non_field_errors": [str(error)]}) from error

    def create(self, validated_data: dict[str, Any]) -> Pet:
        return self._save(Pet(), validated_data)

    def update(self, instance: Pet, validated_data: dict[str, Any]) -> Pet:
        validated_data.pop("owner", None)  # владелец меняется только передачей (transfer)
        return self._save(instance, validated_data)


class WeightSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    class Meta:
        model = PetWeight
        fields = ["id", "date", "weight"]
        extra_kwargs = {"date": {"required": False}}


class PetViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]
    """Питомцы.

    Фильтры: ?owner=<клиент> (текущие питомцы), ?former_of=<клиент> (переданные другим),
    ?status=active|dead, ?species=, ?search=текст (кличка, чип, лаб. №, фамилия владельца).
    """

    serializer_class = PetSerializer
    pagination_class = ClientPagination
    queryset = Pet.objects.all()

    def get_queryset(self) -> QuerySet[Pet]:
        queryset = Pet.objects.select_related("owner", "species", "breed", "color")
        params = self.request.query_params
        if former_of := params.get("former_of"):
            queryset = services.former_pets(get_object_or_404(Client, pk=former_of)).select_related(
                "owner", "species", "breed", "color"
            )
        if owner := params.get("owner"):
            queryset = queryset.filter(owner=owner)
        if status := params.get("status"):
            queryset = queryset.filter(status=status)
        if species := params.get("species"):
            queryset = queryset.filter(species=species)
        if search := params.get("search", "").strip():
            queryset = services.search_pets(queryset, search)
        return queryset

    def _error(self, error: services.ClientError) -> Response:
        return Response({"non_field_errors": [str(error)]}, status=400)

    @action(detail=True, methods=["post"])
    def transfer(self, request: Request, pk: str | None = None) -> Response:
        """Передать питомца другому владельцу: {"owner": "<id клиента>"}."""
        pet = self.get_object()
        new_owner = get_object_or_404(Client, pk=request.data.get("owner"))
        try:
            services.transfer_pet(pet, new_owner)
        except services.ClientError as error:
            return self._error(error)
        return Response(self.get_serializer(pet).data)

    @action(detail=True, methods=["post"])
    def death(self, request: Request, pk: str | None = None) -> Response:
        """Отметить смерть: {"date": "2026-10-29"} (по умолчанию — сегодня)."""
        pet = self.get_object()
        field = serializers.DateField(required=False, allow_null=True)
        death_date = (
            field.run_validation(request.data.get("date")) if request.data.get("date") else None
        )
        try:
            services.mark_dead(pet, death_date)
        except services.ClientError as error:
            return self._error(error)
        return Response(self.get_serializer(pet).data)

    @action(detail=True, methods=["get", "post"])
    def weights(self, request: Request, pk: str | None = None) -> Response:
        """История веса (GET) и новое взвешивание (POST {"weight": "4.25", "date": …})."""
        pet = self.get_object()
        if request.method == "GET":
            return Response(WeightSerializer(pet.weights.all(), many=True).data)
        data = WeightSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            weight = services.add_weight(
                pet, data.validated_data["weight"], data.validated_data.get("date")
            )
        except services.ClientError as error:
            return self._error(error)
        return Response(WeightSerializer(weight).data, status=201)
