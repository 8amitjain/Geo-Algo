from datetime import timedelta, time, datetime

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
import pandas as pd

from market.models import TrendLineCheck
from variables.models import EMASetting
from market.dhan import DHANClient
from market.indicators import EMAIndicator
from market.utils import send_notification_email
from users.models import User
import math


class EMACrossoverChecker:
    def __init__(self, access_token: str):
        self.client = DHANClient(access_token=access_token)

    def run(self) -> None:
        now = timezone.localtime()
        today = now.date()

        recent = TrendLineCheck.objects.filter(
            touched=True,
            purchased=False,
            cross_over_ema=False
        )
        print(recent, "recent")

        for chk in recent:
            # print(chk.id, chk.purchased, chk.trend_line.symbol, chk.trend_line.angles)

            trade_date = today #- timedelta(days=2)
            window_start = datetime.combine(today - timedelta(days=90), datetime.min.time()).replace(hour=9, minute=30)
            window_end = f"{trade_date} 15:00:00"

            df = self.client.get_intraday_ohlc(
                security_id=chk.trend_line.security_id,
                interval=15,
                start_date=window_start.strftime("%Y-%m-%d %H:%M:%S"),
                end_date=window_end
            )

            if df.empty or len(df) < 2:
                continue

            df_d = EMAIndicator.add_emas(df, price_col="close")
            today_bars = df_d.loc[df_d.index.date == trade_date]

            if len(today_bars) < 2:
                continue

            prev_bar = today_bars.iloc[-2]
            last_bar = today_bars.iloc[-1]

            f, s = 5, 25
            col_f, col_s = f"EMA{f}", f"EMA{s}"

            # Skip if EMAs not available
            if pd.isna(prev_bar[col_f]) or pd.isna(prev_bar[col_s]) or pd.isna(last_bar[col_f]) or pd.isna(
                    last_bar[col_s]):
                continue

            ema5 = last_bar[col_f]
            ema25 = last_bar[col_s]

            # Track if EMA5 has ever been below EMA25
            if ema5 < ema25:
                print(1)
                chk.ema5_ever_below_ema25 = True
                chk.save()
                continue  # just mark and wait for crossover

            # If EMA5 is above EMA25
            elif ema5 > ema25:
                if chk.ema5_ever_below_ema25 and not chk.cross_over_ema:
                    print(2)
                    # NEW crossover confirmed — BUY condition
                    # crossed_at = last_bar.name
                    cross_price = last_bar["close"]
                    break_price = last_bar["high"]
                    chk.cross_over_ema = True
                    chk.buy_above_high_price = break_price
                    chk.ema5_ever_below_ema25 = False  # reset for future crossovers
                    chk.save()

                    # send email
                    symbol = chk.trend_line.symbol
                    subject = (
                        f"EMA Cross OVER {symbol} at {now.strftime('%d/%m/%Y %I:%M %p')}"
                    )
                    body = (
                        f"TrendLineCheck ID {chk.id} detected a crossover:\n\n"
                        f" – Pair: EMA(5) / EMA(25)\n"
                        f" – Time: {now:%d/%m/%Y %I:%M %p}\n"
                        f" – Price at crossover: {cross_price:.2f}\n"
                        f" – High to Break: {break_price:.2f}\n"
                    )

                    send_notification_email(
                        subject=subject,
                        message=body,
                        recipient_list=settings.EMAIL_RECIPIENTS
                    )
                    print(subject)

                else:
                    print(3)
                    # Still above, but no fresh crossover
                    continue


class Command(BaseCommand):
    help = "Check for EMA crossovers on the last bar of TrendLineChecks."

    def handle(self, *args, **options):
        now = timezone.localtime()
        # if settings.DEBUG:
        EMACrossoverChecker(settings.DATA_DHAN_ACCESS_TOKEN).run()
        # else:
            # only run during market hours
            # if time(9, 30) <= now.time() <= time(15, 0):
            #     EMACrossoverChecker(settings.DATA_DHAN_ACCESS_TOKEN).run()
            #     self.stdout.write(self.style.SUCCESS("EMA crossover check complete."))
            # else:
            #     self.stdout.write("Outside market hours; skipping crossover check.")
