from django.core.management.base import BaseCommand
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from datetime import timedelta

from users.models import User


class Command(BaseCommand):
    help = "Checks Dhan token expiry and notifies users if expired or within 3 days"

    def handle(self, *args, **options):
        today = timezone.localdate()
        cutoff = today + timedelta(days=3)

        users = User.objects.filter(
            dhan_access_token_expiry__lte=cutoff,
            dhan_access_token__isnull=False,
            email__isnull=False
        )

        for user in users:
            expiry = user.dhan_access_token_expiry
            days_left = (expiry - today).days if expiry else -1

            if days_left < 0:
                subject = "🚫 Your Dhan Access Token Has Expired"
                message = (
                    f"Hi {user.name or user.email},\n\n"
                    "Your Dhan trading access token has already expired. "
                    "Please update it in your account settings to resume trading.\n\n"
                    "Thank you."
                )
            else:
                subject = "⚠️ Dhan Token Expiring Soon"
                message = (
                    f"Hi {user.name or user.email},\n\n"
                    f"Your Dhan access token will expire in {days_left} day(s) (on {expiry}).\n"
                    "Please update your token soon to avoid any disruption.\n\n"
                    "Thank you."
                )

            print(f"Sending email to {user.email} ({subject})")
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )

        self.stdout.write(self.style.SUCCESS("Dhan token check complete."))
