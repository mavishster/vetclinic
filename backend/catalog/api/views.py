"""API каталога: справочники, товары и услуги с единицами и ценами."""

from typing import Any

from django.db.models import QuerySet
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response

from catalog import services
from catalog.models import Item, ItemGroup, ItemUnit, Unit
from core.api.directories import DirectoryViewSet


class UnitViewSet(DirectoryViewSet):
    model = Unit


class ItemGroupViewSet(DirectoryViewSet):
    model = ItemGroup
    extra_fields = ("kind", "markup_percent", "show_in_vaccinations")
    filter_fields = ("kind",)


class ItemUnitSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    id = serializers.UUIDField(required=False)
    unit_name = serializers.CharField(source="unit.name", read_only=True)
    current_price = serializers.SerializerMethodField()
    effective_markup = serializers.SerializerMethodField()

    class Meta:
        model = ItemUnit
        fields = [
            "id", "unit", "unit_name", "ratio", "for_sale", "for_purchase", "pricing", "price",
            "markup_percent", "effective_markup", "price_min", "price_max", "rounding", "barcode",
            "current_price",
        ]  # fmt: skip

    def get_current_price(self, unit: ItemUnit) -> str | None:
        """Цена сейчас: фиксированная или по наценке от себестоимости, указанной вручную."""
        price = services.price_of(unit)
        return str(price) if price is not None else None

    def get_effective_markup(self, unit: ItemUnit) -> str:
        return str(services.effective_markup(unit))


class ItemSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    units = ItemUnitSerializer(many=True, required=False)
    group_name = serializers.CharField(source="group.name", read_only=True)
    base_unit_name = serializers.CharField(source="base_unit.name", read_only=True)

    class Meta:
        model = Item
        fields = [
            "id", "kind", "name", "description", "group", "group_name", "article",
            "base_unit", "base_unit_name", "barcode", "manual_cost", "for_sale", "is_call",
            "is_active", "responsible", "units", "created_at", "updated_at",
        ]  # fmt: skip
        extra_kwargs = {"responsible": {"required": False}}

    def _save(self, item: Item, data: dict[str, Any]) -> Item:
        units = data.pop("units", None)
        responsible = data.pop("responsible", None)
        for field, value in data.items():
            setattr(item, field, value)
        try:
            item = services.save_item(item, units)
        except services.CatalogError as error:
            raise serializers.ValidationError({"non_field_errors": [str(error)]}) from error
        if responsible is not None:
            item.responsible.set(responsible)
        return item

    def create(self, validated_data: dict[str, Any]) -> Item:
        return self._save(Item(), validated_data)

    def update(self, instance: Item, validated_data: dict[str, Any]) -> Item:
        validated_data.pop("kind", None)  # товар не превращается в услугу
        return self._save(instance, validated_data)


class ItemPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class ItemViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]
    """Товары и услуги.

    Фильтры: ?kind=goods|service, ?group=, ?active=true|false,
    ?search=текст (название по словам, точно — артикул и штрихкод).
    """

    serializer_class = ItemSerializer
    pagination_class = ItemPagination
    queryset = Item.objects.all()

    def get_queryset(self) -> QuerySet[Item]:
        queryset = Item.objects.select_related("group", "base_unit").prefetch_related(
            "units__unit", "units__item__group", "responsible"
        )
        params = self.request.query_params
        if kind := params.get("kind"):
            queryset = queryset.filter(kind=kind)
        if group := params.get("group"):
            queryset = queryset.filter(group=group)
        if (active := params.get("active")) is not None:
            queryset = queryset.filter(is_active=active.lower() in {"1", "true"})
        if search := params.get("search", "").strip():
            queryset = services.search_items(queryset, search)
        return queryset

    @action(detail=True, methods=["get"], url_path="price-history")
    def price_history(self, request: Request, pk: str | None = None) -> Response:
        return Response(services.price_history(self.get_object()))
