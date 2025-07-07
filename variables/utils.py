from django.http import JsonResponse
from .models import VibrationPoint


def vibration_point_detail():
    """
    Returns the most‐recent VibrationPoint as JSON.
    """
    vp = VibrationPoint.objects.order_by("-last_modified").first()
    if not vp:
        return "No vibration point configured"

    return str(vp.vibration_point_value)
