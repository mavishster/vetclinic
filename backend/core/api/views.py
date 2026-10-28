from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from core import services


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request: Request) -> Response:
    """Состояние системы. Открыт без входа — нужен для мониторинга."""
    result = services.health()
    return Response(result, status=200 if result["database"] else 503)
