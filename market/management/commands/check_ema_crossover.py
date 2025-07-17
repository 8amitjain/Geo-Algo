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
            # date=today,
        )
        print(recent, "recent")
        for chk in recent:
            # trade_date = ch#k.checked_at.date() #- timedelta(days=2)
            trade_date = today  # - timedelta(days=2)
            print(trade_date)
            # fetch intraday 15m bars from 90d ago through market-close today
            # print(toda)
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

            # compute all EMA series
            df_d = EMAIndicator.add_emas(df, price_col="close")

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

            # check each configured EMASetting
            for setting in EMASetting.objects.all():
                f, s = setting.fast_span, setting.slow_span
                col_f, col_s = f"EMA{f}", f"EMA{s}"

                print(col_f, col_s)
                print(f, s)
                print()

                # ensure both EMAs exist on the last two bars
                if pd.isna(prev_bar[col_f]) or pd.isna(prev_bar[col_s]) or pd.isna(last_bar[col_f]) or pd.isna(last_bar[col_s]):
                    continue

                # was below on the penultimate bar, and above on the last?
                print(last_bar[col_f], last_bar[col_s])
                if last_bar[col_f] > last_bar[col_s]:
                    # fast is above slow right now
                    crossed_at = last_bar.name
                    cross_price = last_bar["close"]
                    break_price = last_bar["high"]
                    used_pair = (f, s)
                    break

            if crossed_at:
                print("INNN")
                # mark as done so we don’t alert again
                chk.cross_over_ema = True
                chk.buy_above_high_price = break_price
                chk.save()
                # TODO add fallback / checks to purchase in all accounts

                # send email
                symbol = chk.trend_line.symbol
                f, s = used_pair
                subject = (
                    f"EMA Cross OVER {symbol} at "
                    f"{now.strftime('%d/%m/%Y %I:%M %p')}"
                )
                body = (
                    f"TrendLineCheck ID {chk.id} detected a crossover:\n\n"
                    f" – Pair: EMA({f}) / EMA({s})\n"
                    f" – Time: {now:%d/%m/%Y %I:%M %p}\n"
                    f" – Price at cross over: {cross_price:.2f}\n"
                    f" – High to Break: {break_price:.2f}\n"
                )
                send_notification_email(
                    subject=subject,
                    message=body,
                    recipient_list=settings.EMAIL_RECIPIENTS
                )
                print(subject)


class Command(BaseCommand):
    help = "Check for EMA crossovers on the last bar of TrendLineChecks."

    def handle(self, *args, **options):
        now = timezone.localtime()
        if settings.DEBUG:
            EMACrossoverChecker(settings.DATA_DHAN_ACCESS_TOKEN).run()
        else:
            # # only run during market hours
            if time(9, 30) <= now.time() <= time(15, 0):
                EMACrossoverChecker(settings.DATA_DHAN_ACCESS_TOKEN).run()
                self.stdout.write(self.style.SUCCESS("EMA crossover check complete."))
            else:
                self.stdout.write("Outside market hours; skipping crossover check.")
