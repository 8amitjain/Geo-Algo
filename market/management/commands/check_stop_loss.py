from datetime import timedelta, time, datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
import pandas as pd
import math

from market.models import TrendLineCheck
from market.dhan import DHANClient
from market.utils import send_notification_email
from users.models import User


class StopLossChecker:
    def __init__(self, access_token: str):
        self.client = DHANClient(access_token=access_token)

    def run(self) -> None:
        now = timezone.localtime()
        today = now.date()
        checks = TrendLineCheck.objects.filter(purchased=True, sold=False)

        for chk in checks:
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

            last_bar = df.iloc[-1]
            stop_loss = chk.stop_loss_price

            if last_bar["low"] > stop_loss:
                continue  # Stop-loss not hit

            sell_price = last_bar["low"]
            sell_time = df.index[-1]

            eligible_users = User.objects.filter(
                trading_enabled=True,
                dhan_access_token__isnull=False
            )

            for user in eligible_users:
                qty = chk.purchase_qty
                if qty <= 0:
                    continue

                symbol = chk.trend_line.symbol
                subject = f"Stop-loss SELL: {symbol} triggered at {now.strftime('%d/%m/%Y %I:%M %p')}"
                body = (
                    f"TrendLineCheck ID {chk.id} triggered SELL:\n"
                    f" – Symbol: {symbol}\n"
                    f" – Stop-loss Hit: ₹{stop_loss:.2f}\n"
                    f" – Sell Price: ₹{sell_price:.2f} at {sell_time.strftime('%H:%M')}\n"
                    f" – Quantity: {qty}\n"
                )
                print(f"Stop-loss hit. Selling {qty} of {symbol} at ₹{sell_price:.2f}")

                try:
                    self.client = DHANClient(access_token=user.dhan_access_token)
                    self.client.place_order(
                        dhan_client_id=user.dhan_client_id,
                        security_id=chk.trend_line.security_id,
                        transaction_type="SELL",
                        quantity=qty,
                        price=sell_price,
                        order_type="MARKET",
                        product_type="CNC",
                        exchange_segment="NSE_EQ",
                        validity="DAY"
                    )

                    chk.sold = True
                    chk.save(update_fields=["sold"])

                    print(f"SELL order placed for {user.email}")
                    send_notification_email(subject, body, [user.email])

                except Exception as e:
                    print(f"SELL order failed for {user.email}: {e}")
                    body += f"\nSell order failed: {e}\n"
                    send_notification_email(subject, body, [user.email])


class Command(BaseCommand):
    help = "Sell stocks if stop-loss has been breached."

    def handle(self, *args, **options):
        # now = timezone.localtime()
        # if settings.DEBUG:
        StopLossChecker(settings.DATA_DHAN_ACCESS_TOKEN).run()
        # else:
        #     if time(9, 30) <= now.time() <= time(15, 30):
        #         StopLossChecker(settings.DATA_DHAN_ACCESS_TOKEN).run()
        #         self.stdout.write(self.style.SUCCESS("Stop-loss check complete."))
        #     else:
        #         self.stdout.write("Outside market hours; skipping stop-loss check.")
