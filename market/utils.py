from django.core.mail import send_mail
from django.conf import settings
from typing import Sequence, Optional
from datetime import timedelta, time

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
import pandas as pd

from market.models import TrendLineCheck
from market.dhan import DHANClient
from users.models import User
import math


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


def buy_sell_stock(risk_per_unit, cross_price, security_id, symbol, transaction_type):
    eligible_users = User.objects.filter(
        trading_enabled=True,
        dhan_access_token__isnull=False,
    )
    for user in eligible_users:
        print(f"{user.email} | Risk per unit: ₹{risk_per_unit:.2f} | Risk per trade: ₹{user.risk_per_trade}")

        qty = math.floor(user.risk_per_trade / risk_per_unit)
        # Place order using Dhan API
        client = DHANClient(access_token=user.dhan_access_token)
        client.place_order(
            dhan_client_id=user.dhan_client_id,
            security_id=security_id,
            transaction_type=transaction_type,
            quantity=qty,
            price=cross_price,
            order_type="MARKET",  # or "LIMIT" if you want to use a specific price
            product_type="CNC",
            exchange_segment="NSE_EQ",  # or "BSE" as appropriate
            validity="DAY",
        )
        print(f"Order placed {transaction_type}: {qty} shares of {symbol} at approx ₹{cross_price:.2f}")
        now = timezone.localtime()
        subject = (
            f"{transaction_type} {symbol} at "
            f"{now.strftime('%d/%m/%Y %I:%M %p')}"
        )

        body = f" – Order: {qty} shares placed at ₹{cross_price:.2f}\n"
        send_notification_email(
            subject=subject,
            message=body,
            recipient_list=settings.EMAIL_RECIPIENTS
        )
