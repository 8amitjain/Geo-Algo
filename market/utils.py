from django.core.mail import send_mail
from django.conf import settings
from typing import Sequence, Optional


def send_notification_email(
    subject: str,
    message: str,
    recipient_list: Sequence[str],
    from_email: Optional[str] = None,
    fail_silently: bool = False,
) -> int:
    """
    Sends a plain-text email using Django’s send_mail.
    Returns the number of successfully delivered messages (0 or 1).
    """
    from_email = from_email or settings.DEFAULT_FROM_EMAIL
    return send_mail(
        subject,
        message,
        from_email,
        list(recipient_list),
        fail_silently=fail_silently,
    )
