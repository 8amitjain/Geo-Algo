from django.http import JsonResponse
from .models import VibrationPoint


def vibration_point_detail(request):
    """
    GET /variables/vibration-point/
    Returns the most‐recent VibrationPoint as JSON.
    """
    vp = VibrationPoint.objects.order_by("-last_modified").first()
    if not vp:
        return JsonResponse(
            {"error": "No vibration point configured"},
            status=404
        )

    return JsonResponse({
        "vibration_point_value": str(vp.vibration_point_value),
        "last_modified": vp.last_modified.isoformat(),
    })
