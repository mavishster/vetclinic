"""API каталога: справочники, товары и услуги с единицами и ценами."""

from typing import Any

from django.db.models import QuerySet
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response

from catalog import services
from catalog.models import CombinationLine, Item, ItemGroup, ItemUnit, Kind, Unit
from core import services as core
from core.api.directories import DirectoryViewSet
from core.api.permissions import can_view_cost


def _text(value: Any) -> str | None:
    """Деньги и количества в ответе — строкой, как во всём API (без потерь точности)."""
    return None if value is None else str(value)


class UnitViewSet(DirectoryViewSet):
    model = Unit


class ItemGroupViewSet(DirectoryViewSet):
    model = ItemGroup
    extra_fields = ("kind", "markup_percent", "prevention_kind")
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


class CombinationLineSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    item_name = serializers.CharField(source="item_unit.item.name", read_only=True)
    item_kind = serializers.CharField(source="item_unit.item.kind", read_only=True)
    unit_name = serializers.CharField(source="item_unit.unit.name", read_only=True)
    current_price = serializers.SerializerMethodField()

    class Meta:
        model = CombinationLine
        fields = [
            "item_unit", "item_name", "item_kind", "unit_name", "quantity", "price_override",
            "current_price",
        ]  # fmt: skip

    def get_current_price(self, line: CombinationLine) -> str | None:
        """Цена позиции по прайсу — подсказка, если своя цена не задана."""
        price = services.price_of(line.item_unit)
        return str(price) if price is not None else None


class ItemSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    units = ItemUnitSerializer(many=True, required=False)
    lines = CombinationLineSerializer(many=True, required=False)
    combo_price = serializers.SerializerMethodField()
    group_name = serializers.CharField(source="group.name", read_only=True)
    base_unit_name = serializers.CharField(source="base_unit.name", read_only=True)

    class Meta:
        model = Item
        fields = [
            "id", "kind", "name", "description", "group", "group_name", "article",
            "base_unit", "base_unit_name", "barcode", "manual_cost", "for_sale", "combo_only",
            "stock_tracked", "prevention_kind", "is_call",
            "is_active", "responsible", "units", "is_template", "print_mode", "lines",
            "combo_price", "created_at", "updated_at",
        ]  # fmt: skip
        extra_kwargs = {"responsible": {"required": False}, "base_unit": {"required": False}}

    def get_combo_price(self, item: Item) -> str | None:
        if item.kind != Kind.COMBO:
            return None
        price = services.combination_price(item)
        return str(price) if price is not None else None

    def _save(self, item: Item, data: dict[str, Any]) -> Item:
        units = data.pop("units", None)
        lines = data.pop("lines", None)
        responsible = data.pop("responsible", None)
        for field, value in data.items():
            setattr(item, field, value)
        try:
            if item.kind == Kind.COMBO:
                item = services.save_combination(item, lines)
            else:
                if not item.base_unit_id:
                    raise services.CatalogError("Укажите единицу учёта.")
                item = services.save_item(item, units)
        except services.CatalogError as error:
            raise serializers.ValidationError({"non_field_errors": [str(error)]}) from error
        if responsible is not None:
            item.responsible.set(responsible)
        return item

    def create(self, validated_data: dict[str, Any]) -> Item:
        return self._save(Item(), validated_data)

    def to_representation(self, item: Item) -> dict[str, Any]:
        data = super().to_representation(item)
        if not can_view_cost(self.context.get("request")):
            data["manual_cost"] = None  # себестоимость — только с особым правом
        return data

    def update(self, instance: Item, validated_data: dict[str, Any]) -> Item:
        validated_data.pop("kind", None)  # товар не превращается в услугу
        if not can_view_cost(self.context.get("request")):
            validated_data.pop("manual_cost", None)  # не видел — не может и стереть
        return self._save(instance, validated_data)


class ItemPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class ItemViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]
    """Товары и услуги.

    Фильтры: ?kind=goods|service|combo (можно через запятую), ?group=, ?active=true|false,
    ?tracked=yes|no (складской учёт), ?not_for_sale=true,
    ?search=текст (название по словам, точно — артикул и штрихкод).
    """

    serializer_class = ItemSerializer
    pagination_class = ItemPagination
    queryset = Item.objects.all()

    def get_queryset(self) -> QuerySet[Item]:
        queryset = Item.objects.select_related("group", "base_unit").prefetch_related(
            "units__unit", "units__item__group", "responsible",
            "lines__item_unit__item__group", "lines__item_unit__unit",
        )  # fmt: skip
        params = self.request.query_params
        if kind := params.get("kind"):
            queryset = queryset.filter(kind__in=kind.split(","))
        if group := params.get("group"):
            queryset = queryset.filter(group=group)
        if (active := params.get("active")) is not None:
            queryset = queryset.filter(is_active=active.lower() in {"1", "true"})
        if (tracked := params.get("tracked")) in {"yes", "no"}:
            queryset = queryset.filter(kind=Kind.GOODS, stock_tracked=tracked == "yes")
        if params.get("not_for_sale", "").lower() in {"1", "true"}:
            queryset = queryset.filter(for_sale=False)
        if search := params.get("search", "").strip():
            queryset = services.search_items(queryset, search)
        return queryset

    @action(detail=True, methods=["post"], url_path="reset-prices")
    def reset_prices(self, request: Request, pk: str | None = None) -> Response:
        """Комбинация: сбросить свои цены позиций — дальше они идут по прайсу."""
        item = self.get_object()
        services.reset_combination_prices(item)
        return Response(self.get_serializer(item).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Удалить можно только то, чем не пользовались (склад, медкарта, комбинации…);
        иначе — сделать неактивным: позиция пропадёт из выбора, а история сохранится."""
        item = self.get_object()
        used = core.usage_count(item) + sum(core.usage_count(unit) for unit in item.units.all())
        if used:
            raise ValidationError(
                {"non_field_errors": [
                    f"«{item}» уже используется (записей: {used}) — удалить нельзя. "
                    "Снимите галочку «Активен»: позиция перестанет предлагаться для выбора."
                ]}
            )  # fmt: skip
        item.delete()
        return Response(status=204)

    @action(detail=True, methods=["get"])
    def combinations(self, request: Request, pk: str | None = None) -> Response:
        """В каких комбинациях есть позиция."""
        return Response(
            [
                {"id": str(c.pk), "name": c.name}
                for c in services.combinations_with(self.get_object())
            ]
        )

    @action(detail=True, methods=["get"], url_path="removed-units")
    def removed_units(self, request: Request, pk: str | None = None) -> Response:
        """Убранные единицы позиции — посмотреть, какие были и по какой цене."""
        return Response(
            [
                {"unit_name": u.unit.name, "ratio": str(u.ratio), "pricing": u.pricing,
                 "price": _text(u.price), "markup_percent": _text(u.markup_percent),
                 "removed_at": u.updated_at}
                for u in services.removed_units(self.get_object())
            ]
        )  # fmt: skip

    @action(detail=True, methods=["get"], url_path="price-history")
    def price_history(self, request: Request, pk: str | None = None) -> Response:
        return Response(services.price_history(self.get_object()))
