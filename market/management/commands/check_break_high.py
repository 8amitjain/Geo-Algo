from datetime import timedelta, time, datetime

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
import pandas as pd

from market.models import TrendLineCheck
from market.dhan import DHANClient
from market.utils import send_notification_email
from users.models import User
import math


class BreakoutChecker:
    def __init__(self, access_token: str):
        self.client = DHANClient(access_token=access_token)

    def run(self) -> None:
        now = timezone.localtime()
        today = now.date()
        recent = TrendLineCheck.objects.filter(
            touched=True,
            purchased=False,
            cross_over_ema=True,
        )

        for chk in recent:
            trade_date = today
            window_start = datetime.combine(today - timedelta(days=90), datetime.min.time()).replace(hour=9, minute=30, second=0)
            window_end = f"{trade_date} 15:00:00"

            df = self.client.get_intraday_ohlc(
                security_id=chk.trend_line.security_id,
                interval=15,
                start_date=window_start.strftime("%Y-%m-%d %H:%M:%S"),
                end_date=window_end
            )
            if df.empty or len(df) < 2:
                continue

            # Look for bars after the touched bar
            touch_date = chk.date
            price_trigger = chk.buy_above_high_price

            # ✅ Check if the latest bar's high crosses the trigger
            last_bar = df.iloc[-1]
            if last_bar["high"] <= price_trigger:
                print("IN last_bar high")
                continue  # No buy signal from latest bar

            cross_price = last_bar["high"]
            cross_time = df.index[-1]

            # Get low of the day from touch day for risk calculation
            bars_on_touch_day = df[df.index.date == touch_date]
            if bars_on_touch_day.empty:
                print("IN bars_on_touch_day")
                continue

            low_of_day = bars_on_touch_day["low"].min()
            risk_per_unit = abs(cross_price - low_of_day)
            stop_loss = low_of_day

            if risk_per_unit == 0:
                print(f"Risk per unit is 0 for {chk.trend_line.symbol}; skipping.")
                continue

            chk.purchased = True
            chk.stop_loss_price = low_of_day  # calculated earlier
            chk.save(update_fields=["purchased", "stop_loss_price"])

            eligible_users = User.objects.filter(
                trading_enabled=True,
                dhan_access_token__isnull=False
            )

            for user in eligible_users:
                qty = math.floor(user.risk_per_trade / risk_per_unit)
                if qty <= 0:
                    continue
                chk.purchase_qty = qty  # calculated earlier
                chk.save(update_fields=["purchase_qty"])

                symbol = chk.trend_line.symbol
                subject = f"Purchase {symbol} triggered at {now.strftime('%d/%m/%Y %I:%M %p')}"
                body = (
                    f"TrendLineCheck ID {chk.id} triggered buy:\n"
                    f" – Symbol: {symbol}\n"
                    f" – Price Trigger: ₹{price_trigger:.2f}\n"
                    f" – Executed Price: ₹{cross_price:.2f} at {cross_time.strftime('%H:%M')}\n"
                    f" – Risk/Unit: ₹{risk_per_unit:.2f}\n"
                    f" – Quantity: {qty}\n"
                    f" – Stop-loss: ₹{stop_loss:.2f}\n"
                )
                print(f"Order placed: {qty} shares of {symbol} at approx ₹{cross_price:.2f}")

                try:
                    self.client = DHANClient(access_token=user.dhan_access_token)
                    self.client.place_order(
                        dhan_client_id=user.dhan_client_id,
                        security_id=chk.trend_line.security_id,
                        transaction_type="BUY",
                        quantity=qty,
                        price=cross_price,
                        order_type="MARKET",
                        product_type="CNC",
                        exchange_segment="NSE_EQ",
                        validity="DAY"
                    )

                    print(f"Order placed for {user.email}: {qty} shares of {symbol} at ₹{cross_price:.2f}")
                    send_notification_email(subject, body, [user.email])

                except Exception as e:
                    print(f"Order failed for {user.email} ({symbol}): {e}")
                    body += f"\nOrder failed: {e}\n"
                    send_notification_email(subject, body, [user.email])


class Command(BaseCommand):
    help = "Check for Breakout after cross over TrendLineChecks."

    def handle(self, *args, **options):
        now = timezone.localtime()
        if settings.DEBUG:
            BreakoutChecker(settings.DATA_DHAN_ACCESS_TOKEN).run()
        else:
            # # only run during market hours
            if time(9, 30) <= now.time() <= time(15, 0):
                BreakoutChecker(settings.DATA_DHAN_ACCESS_TOKEN).run()
                self.stdout.write(self.style.SUCCESS("Breakout check complete."))
            else:
                self.stdout.write("Outside market hours; skipping crossover check.")
