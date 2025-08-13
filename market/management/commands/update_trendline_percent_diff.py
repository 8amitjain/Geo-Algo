from django.core.management.base import BaseCommand
from django.utils import timezone
from market.models import TrendLine
from market.dhan import DHANClient, TrendLine as CoreTrendLine
from decimal import Decimal
from datetime import datetime, timedelta
import pandas as pd
from requests.exceptions import HTTPError
from geo_algo import settings


class Command(BaseCommand):
    help = "Update cached percent difference for all trend lines at 4 PM"

    def handle(self, *args, **kwargs):
        now = timezone.now()
        client = DHANClient(access_token=settings.DATA_DHAN_ACCESS_TOKEN)
        updated = 0

        # for tl in TrendLine.objects.all():
        for tl in TrendLine.objects.filter(percent_difference_cached=None):
            # try:
                # Step 1: Determine last available trading day
                bar_close = None
                trendline_date = None

                for offset in range(0, 5):
                    candidate_day = (now - timedelta(days=offset)).date()
                    start_ts = datetime.combine(candidate_day, datetime.min.time())
                    end_ts = datetime.combine(candidate_day, datetime.max.time())

                    intraday = client.get_intraday_ohlc(
                        security_id=tl.security_id,
                        interval=15,
                        start_date=start_ts.strftime("%Y-%m-%d %H:%M:%S"),
                        end_date=end_ts.strftime("%Y-%m-%d %H:%M:%S"),
                    )

                    if not intraday.empty:
                        bar_close = Decimal(str(intraday["close"].iat[-1]))
                        trendline_date = candidate_day
                        break

                if not bar_close or not trendline_date:
                    continue

                # Step 2: Get or compute trendline price
                rec = next(
                    (pt for pt in (tl.line_data or []) if pt["date"] == trendline_date.strftime("%Y-%m-%d")),
                    None
                )

                if not rec:
                    full_df = client.get_full_history(tl.security_id)
                    core_tl = CoreTrendLine(
                        full_df=full_df,
                        start_date=tl.start_date,
                        angle_deg=tl.angles[0],
                        price_to_bar_ratio=tl.price_to_bar_ratio,
                    )
                    _, ys = core_tl.get_points()
                    for dt, val in zip(core_tl.dates, ys):
                        if dt.date() == trendline_date:
                            rec = {"date": dt.strftime("%Y-%m-%d"), "value": float(val)}
                            break

                if not rec:
                    continue

                trendline_price = Decimal(str(rec["value"]))
                percent_diff = ((bar_close - trendline_price) / trendline_price) * 100
                tl.percent_difference_cached = round(percent_diff, 2)
                tl.percent_diff_updated_date = trendline_date
                tl.save()
                updated += 1

            # except Exception as e:
            #     print(f"Failed to update trend line {tl.pk}: {e}")

        self.stdout.write(self.style.SUCCESS(f"{updated} trend lines updated."))
