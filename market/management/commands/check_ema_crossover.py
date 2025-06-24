from datetime import timedelta, time, datetime
from django.core.management.base import BaseCommand
from django.utils import timezone

from geo_algo import settings
from market.models import TrendLineCheck
from market.dhan import DHANClient
from market.indicators import EMAIndicator
from market.utils import send_notification_email


class EMACrossoverChecker:
    """
    For each TrendLineCheck marked touched in the past day, fetch 15-minute bars
    covering the last 90 days (to seed the EMA), then detect any new EMA(5/26)
    crossover that occurs today only.
    """

    def __init__(self, access_token: str):
        self.client = DHANClient(access_token=access_token)

    def run(self) -> None:
        now = timezone.localtime()
        day_ago = now - timedelta(days=1)

        recent_checks = TrendLineCheck.objects.filter(
            touched=True,
            checked_at__gte=day_ago,
            purchased=False
        )

        for chk in recent_checks:
            # 1) Determine the 90-day window ending today at 15:00
            # start_dt_full: datetime = datetime.combine(chk.date, time.min)

            start_dt_full = chk.checked_at
            trading_date = start_dt_full.date()
            window_start = start_dt_full - timedelta(days=90)
            # force window_start to 09:30 of that day
            window_start = window_start.replace(hour=9, minute=30, second=0, microsecond=0)

            window_end = trading_date.strftime("%Y-%m-%d") + " 15:00:00"

            # 2) Fetch 15-minute OHLC from 90 days ago through today at 15:00
            df_15m = self.client.get_intraday_ohlc(
                security_id=chk.trend_line.security_id,
                interval=15,
                start_date=window_start.strftime("%Y-%m-%d %H:%M:%S"),
                end_date=window_end
            )
            if df_15m.empty:
                continue

            # 3) Compute EMAs on the full 90-day history
            df_ema = EMAIndicator.add_emas(df_15m, price_col="close")

            # 4) Slice out only 'today' bars (from 09:30 to 15:00)
            df_today = df_ema.loc[
                df_ema.index.date == trading_date
            ]
            if df_today.empty:
                continue

            ema5 = df_today["EMA5"]
            ema26 = df_today["EMA26"]

            # 5) Ensure we only look for a fresh crossover: EMA5 must have been below EMA26
            #    at the very first timestamp of today (if both exist)
            if len(ema5) == 0 or len(ema26) == 0:
                continue

            first_idx = df_today.index[0]
            if ema5.loc[first_idx] > ema26.loc[first_idx]:
                # Already above at market open – skip if no new crossover
                was_below = False
            else:
                was_below = True

            crossover_time = None
            for timestamp, row in df_today.iterrows():
                if not was_below:
                    if row["EMA5"] < row["EMA26"]:
                        was_below = True
                else:
                    if row["EMA5"] > row["EMA26"]:
                        crossover_time = timestamp
                        close_price = row["close"]
                        break

            if crossover_time:
                # Update the object purchased.
                chk.purchased = True
                chk.save()

                # Format subject and body with real variables
                symbol = chk.trend_line.symbol
                subject = f"📈 EMA Crossover for {symbol} at {crossover_time.strftime('%d/%m/%Y %I:%M %p')}"
                body = (
                    f"EMA(5) has crossed above EMA(26) for **{symbol}**.\n\n"
                    f"• Time of crossover: {crossover_time.strftime('%d/%m/%Y %I:%M %p')}\n"
                    f"• Price at crossover: {close_price:.2f}\n"
                    f"• Detected by TrendLineCheck ID: {chk.id}\n"
                )

                # send the email
                send_notification_email(
                    subject=subject,
                    message=body,
                    recipient_list=["8amitjain@gmail.com"],
                )

                # TODO ADD BUY CODE

                print(f"EMA crossover detected for {chk.trend_line} at {crossover_time}")


class Command(BaseCommand):
    help = "Check for new 15-min EMA crossover on today’s bars after a trend-line was touched."

    def handle(self, *args, **options):
        now = timezone.localtime()
        if not (time(9, 30) <= now.time() <= time(15, 0)):
            return
        else:
            checker = EMACrossoverChecker(access_token=settings.DATA_DHAN_ACCESS_TOKEN)
            checker.run()
            self.stdout.write(self.style.SUCCESS("EMA crossover check complete."))
