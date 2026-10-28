"""API печатных форм: шаблоны, виды форм с переменными, предпросмотр."""

from typing import Any

from django.http import HttpResponse
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from core import printing, services
from core.api.directories import DirectorySerializer, DirectoryViewSet
from core.models import PrintTemplate


class PrintTemplateSerializer(DirectorySerializer):
    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        kind = attrs.get("kind", getattr(self.instance, "kind", ""))
        body = attrs.get("body", getattr(self.instance, "body", ""))
        try:
            services.validate_print_template(kind, body)
        except printing.PrintTemplateError as error:
            raise serializers.ValidationError({"body": str(error)}) from error
        return attrs


class PreviewSerializer(serializers.Serializer):  # type: ignore[type-arg]
    kind = serializers.CharField()
    body = serializers.CharField()


class PrintTemplateViewSet(DirectoryViewSet):
    """Шаблоны печатных форм. Фильтр ?kind=… — формы одного вида."""

    model = PrintTemplate
    extra_fields = ("kind", "body")
    filter_fields = ("kind",)
    serializer_base = PrintTemplateSerializer

    @action(detail=False, methods=["get"])
    def kinds(self, request: Request) -> Response:
        """Виды печатных форм, их переменные и фильтры — для редактора шаблонов."""
        return Response(
            {
                "kinds": [
                    {
                        "code": kind.code,
                        "title": kind.title,
                        "variables": {**printing.COMMON_VARIABLES, **kind.variables},
                    }
                    for kind in printing.kinds()
                ],
                "filters": printing.FILTERS_HELP,
            }
        )

    @action(detail=False, methods=["post"])
    def preview(self, request: Request) -> Response:
        """HTML несохранённого шаблона на примере данных — для живого предпросмотра."""
        data = PreviewSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        template = PrintTemplate(kind=data.validated_data["kind"], body=data.validated_data["body"])
        try:
            html = services.render_print_sample(template, as_pdf=False)
        except printing.PrintTemplateError as error:
            return Response({"body": [str(error)]}, status=400)
        return Response({"html": html})

    @action(detail=True, methods=["get"])
    def sample(self, request: Request, pk: str | None = None) -> HttpResponse:
        """PDF сохранённого шаблона на примере данных."""
        pdf = services.render_print_sample(self.get_object())
        return HttpResponse(pdf, content_type="application/pdf")
