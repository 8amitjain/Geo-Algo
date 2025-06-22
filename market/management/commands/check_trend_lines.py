# market/management/commands/check_trend_lines.py

from decimal import Decimal
from datetime import timedelta, time

from django.core.management.base import BaseCommand
from django.utils import timezone

from geo_algo import settings
from market.models import TrendLine, TrendLineCheck
from market.dhan import DHANClient, TrendLine as CoreTrendLine


# RUN every 15 MIN.
class TrendLineChecker:
    """
    Re-computes each stored TrendLine’s line_data (now including yesterday),
    updates the model, and then records whether yesterday’s price touched it.
    """

    def __init__(self, api_token: str, api_token_data: str):
        # api_token for metadata/listing (not used here),
        # api_token_data for full OHLC history
        self.client_data = DHANClient(access_token=api_token_data)

    def run(self) -> None:
        # TODO - Add 0.5% up or down allowance for bar touch
        # TODO Check every 15 mins for candle touch
        # we want to check the bar *for yesterday* (market data up to yesterday)
        yesterday = timezone.localtime().date() - timedelta(days=2)

        # pick all lines that start on/before yesterday and haven't yet been touched
        to_check = TrendLine.objects.filter(
            start_date__lte=yesterday
        ).exclude(
            checks__touched=True
        )

        for tl in to_check:
            # 1) Recompute full line_data from listing → last bar
            full_df = self.client_data.get_full_history(tl.security_id)
            angle = tl.angles[0]             # your model stores one-angle-per-record
            ratio = tl.price_to_bar_ratio

            core_tl = CoreTrendLine(
                full_df=full_df,
                start_date=tl.start_date,
                angle_deg=angle,
                price_to_bar_ratio=ratio,
            )
            xs, ys = core_tl.get_points()

            # rebuild JSON payload (date strings + prices)
            new_line_data = [
                {"date": dt.strftime("%Y-%m-%d"), "value": float(val)}
                for dt, val in zip(core_tl.dates, ys)
            ]

            # 2) Save updated line_data back to the model
            tl.line_data = new_line_data
            tl.save(update_fields=["line_data"])

            # 3) Extract yesterday’s trend price
            date_str = yesterday.strftime("%Y-%m-%d")
            rec = next((p for p in new_line_data if p["date"] == date_str), None)
            if rec is None:
                # no data point for yesterday
                continue

            line_price = Decimal(str(rec["value"]))

            # 4) Fetch actual OHLC for yesterday
            df = self.client_data.get_ticker_data(
                security_id=tl.security_id,
                from_date=date_str,
            )
            # assume the first row corresponds to 'date_str'
            actual_low = Decimal(str(df["low"].iloc[0]))
            actual_high = Decimal(str(df["high"].iloc[0]))

            # 5) Determine if 'touched'
            touched = (
                actual_low <= line_price <= actual_high
            )

            # 6) Record the check
            TrendLineCheck.objects.update_or_create(
                trend_line=tl,
                date=yesterday,
                defaults={
                    "line_price":    line_price,
                    "actual_price":  actual_low,
                    "touched":       touched,
                },
            )


class Command(BaseCommand):
    help = "Recompute stored trend-lines through yesterday and check if price touched."

    def handle(self, *args, **options):
        now = timezone.localtime()
        if not (time(9, 30) <= now.time() <= time(15, 0)):
            return

        else:
            checker = TrendLineChecker(
                api_token=settings.AMIT_TRADING_DHAN_ACCESS_TOKEN,
                api_token_data=settings.DATA_DHAN_ACCESS_TOKEN
            )
            checker.run()
            self.stdout.write(self.style.SUCCESS("Trend lines re-computed and checked."))
