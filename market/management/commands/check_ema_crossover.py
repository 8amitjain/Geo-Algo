from datetime import timedelta, time

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
import pandas as pd

from market.models import TrendLineCheck
from variables.models import DEMASetting
from market.dhan import DHANClient
from market.indicators import DEMAIndicator
from market.utils import send_notification_email

import math


class EMACrossoverChecker:
    def __init__(self, access_token: str):
        self.client = DHANClient(access_token=access_token)

    def run(self) -> None:
        now = timezone.localtime()
        recent = TrendLineCheck.objects.filter(
            touched=True,
            purchased=False,
        )

        for chk in recent:
            trade_date = chk.checked_at.date()

            # fetch intraday 15m bars from 90d ago through market-close today
            window_start = (
                chk.checked_at - timedelta(days=90)
            ).replace(hour=9, minute=30, second=0, microsecond=0)
            window_end = f"{trade_date} 15:00:00"

            df = self.client.get_intraday_ohlc(
                security_id=chk.trend_line.security_id,
                interval=15,
                start_date=window_start.strftime("%Y-%m-%d %H:%M:%S"),
                end_date=window_end
            )
            if df.empty or len(df) < 2:
                continue

            # compute all DEMA series
            df_d = DEMAIndicator.add_demas(df, price_col="close")

            # restrict to today’s bars
            today_bars = df_d.loc[df_d.index.date == trade_date]
            if len(today_bars) < 2:
                continue

            # grab the last two bars
            prev_bar = today_bars.iloc[-2]
            last_bar = today_bars.iloc[-1]

            crossed_at = None
            cross_price = None
            used_pair = None

            # check each configured DEMASetting
            for setting in DEMASetting.objects.all():
                f, s = setting.fast_span, setting.slow_span
                col_f, col_s = f"DEMA{f}", f"DEMA{s}"

                print(col_f, col_s)
                print(f, s)
                print()

                # ensure both DEMAs exist on the last two bars
                if pd.isna(prev_bar[col_f]) or pd.isna(prev_bar[col_s]) or pd.isna(last_bar[col_f]) or pd.isna(last_bar[col_s]):
                    continue

                # was below on the penultimate bar, and above on the last?
                print(prev_bar[col_f], prev_bar[col_s])
                if last_bar[col_f] > last_bar[col_s]:
                    # fast is above slow right now
                    crossed_at = last_bar.name
                    cross_price = last_bar["close"]
                    used_pair = (f, s)
                    break

            if crossed_at:
                # mark as done so we don’t alert again
                chk.purchased = True
                chk.save(update_fields=["purchased"])

                # send email
                symbol = chk.trend_line.symbol
                f, s = used_pair
                subject = (
                    f"Purchase {symbol} at "
                    f"{now.strftime('%d/%m/%Y %I:%M %p')}"
                )
                body = (
                    f"TrendLineCheck ID {chk.id} detected a crossover:\n\n"
                    f" – Pair: DEMA({f}) / DEMA({s})\n"
                    f" – Time: {now:%d/%m/%Y %I:%M %p}\n"
                    f" – Price: {cross_price:.2f}\n"
                )

                try:
                    # Determine quantity to buy based on risk
                    # low_of_day = today_bars["low"].min()
                    bars_on_touched_day = df_d.loc[df_d.index.date == chk.checked_at.date()]

                    touch_time = pd.to_datetime(chk.checked_at)
                    touch_time = touch_time.tz_localize(
                        None) if bars_on_touched_day.index.tz is None else touch_time.tz_convert(
                        bars_on_touched_day.index.tz)

                    bars_until_touch = bars_on_touched_day[bars_on_touched_day.index <= touch_time]

                    if bars_until_touch.empty:
                        print(f"No bars found up to touch time for {chk.trend_line.symbol}; skipping.")
                        continue

                    low_of_day = bars_until_touch["low"].min()

                    risk_per_unit = abs(cross_price - low_of_day)
                    if risk_per_unit == 0:
                        print("Risk per unit is 0; skipping order placement.")
                    else:
                        qty = math.floor(500 / risk_per_unit)

                        # Place order using Dhan API
                        self.client = DHANClient(access_token=settings.AMIT_TRADING_DHAN_ACCESS_TOKEN)
                        self.client.place_order(
                            dhan_client_id=settings.AMIT_CLIENT_ID,
                            security_id=chk.trend_line.security_id,
                            transaction_type="BUY",
                            quantity=qty,
                            price=cross_price,
                            order_type="MARKET",  # or "LIMIT" if you want to use a specific price
                            product_type="CNC",
                            exchange_segment="NSE_EQ",  # or "BSE" as appropriate
                            validity="DAY"
                        )

                        self.client = DHANClient(access_token=settings.ANAND_TRADING_DHAN_ACCESS_TOKEN)
                        self.client.place_order(
                            dhan_client_id=settings.ANAND_CLIENT_ID,
                            security_id=chk.trend_line.security_id,
                            transaction_type="BUY",
                            quantity=qty,
                            price=cross_price,
                            order_type="MARKET",  # or "LIMIT" if you want to use a specific price
                            product_type="CNC",
                            exchange_segment="NSE_EQ",  # or "BSE" as appropriate
                            validity="DAY"
                        )
                        print(f"Order placed: {qty} shares of {symbol} at approx ₹{cross_price:.2f}")
                        body += f" – Order: {qty} shares placed at ₹{cross_price:.2f}\n"

                except Exception as e:
                    print(f"Failed to place order for {symbol}: {e}")
                    body += f"\n Order placement failed: {e}\n"

                send_notification_email(
                    subject=subject,
                    message=body,
                    recipient_list=settings.EMAIL_RECIPIENTS
                )
                print(subject)


class Command(BaseCommand):
    help = "Check for DEMA crossovers on the last bar of TrendLineChecks."

    def handle(self, *args, **options):
        now = timezone.localtime()
        # only run during market hours
        if time(9, 30) <= now.time() <= time(15, 0):
            EMACrossoverChecker(settings.DATA_DHAN_ACCESS_TOKEN).run()
            self.stdout.write(self.style.SUCCESS("DEMA crossover check complete."))
        else:
            self.stdout.write("Outside market hours; skipping crossover check.")
