from decimal import Decimal
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from geo_algo import settings
from market.models import TrendLine, TrendLineCheck
from market.dhan import DHANClient, TrendLine as CoreTrendLine
from market.utils import send_notification_email
from variables.utils import vibration_point_detail


class TrendLineChecker:
    """
    Recomputes each stored TrendLine’s line_data through the last bar,
    then, every 15 min during market hours, fetches the most-recent 15m
    bar and marks whether it touched the trend line (± vibration tolerance),
    only if previous 10 EOD candles were above the trendline (with tolerance).
    """

    def __init__(self, api_token_data: str):
        self.client = DHANClient(access_token=api_token_data)

    def run(self) -> None:
        now = timezone.localtime()
        today = now.date()

        to_check = TrendLine.objects.filter(
            start_date__lte=today
        ).exclude(
            checks__touched=True
        )
        print(to_check, "to_check")

        for tl in to_check:
            print(tl.symbol)
            full_df = self.client.get_full_history(tl.security_id)
            angle = tl.angles[0]
            ratio = tl.price_to_bar_ratio

            core_tl = CoreTrendLine(
                full_df=full_df,
                start_date=tl.start_date,
                angle_deg=angle,
                price_to_bar_ratio=ratio,
            )

            # rebuild JSON line_data
            xs, ys = core_tl.get_points()
            tl.line_data = [
                {"date": dt.strftime("%Y-%m-%d"), "value": float(val)}
                for dt, val in zip(core_tl.dates, ys)
            ]
            tl.save(update_fields=["line_data"])

            # today's theoretical trendline price
            rec = next(
                (pt for pt in tl.line_data if pt["date"] == today.strftime("%Y-%m-%d")),
                None
            )
            if not rec:
                continue

            line_price = Decimal(str(rec["value"]))
            vibration_point = Decimal(str(vibration_point_detail()))
            tol = (line_price * vibration_point).quantize(Decimal("0.01"))
            lower_bnd = line_price - tol
            upper_bnd = line_price + tol

            # fetch most recent 15-min candle
            end_ts = now.strftime("%Y-%m-%d %H:%M:%S")
            start_ts = (now - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
            intraday = self.client.get_intraday_ohlc(
                security_id=tl.security_id,
                interval=15,
                start_date=start_ts,
                end_date=end_ts,
            )

            if intraday.empty:
                continue

            bar_low = Decimal(str(intraday["low"].iat[-1]))
            bar_high = Decimal(str(intraday["high"].iat[-1]))
            bar_close = Decimal(str(intraday["close"].iat[-1]))

            # check current bar touch
            current_touched = (bar_high >= lower_bnd) and (bar_low <= upper_bnd)

            # validate EOD condition only if current touched
            touched = False
            if current_touched:
                # fetch last 10 EOD candles before today
                eod_history = self.client.get_ticker_data(
                    security_id=tl.security_id,
                    from_date=(today - timedelta(days=30)).strftime("%Y-%m-%d"),
                )

                if not eod_history.empty:
                    last_10_eod = eod_history.tail(5)

                    # map of date -> trendline value
                    line_map = {pt["date"]: Decimal(str(pt["value"])) for pt in tl.line_data}

                    def get_date_str(val):
                        if hasattr(val, "strftime"):
                            return val.strftime("%Y-%m-%d")
                        return str(val).split(" ")[0]

                    all_above = True
                    for idx, row in last_10_eod.iterrows():
                        # get timestamp from column if present, else from index
                        if "timestamp" in last_10_eod.columns:
                            ts_val = row["timestamp"]
                        else:
                            ts_val = idx  # fallback: index is datetime
                        row_date = get_date_str(ts_val)

                        trend_price = line_map.get(row_date)
                        if not trend_price:
                            all_above = False
                            break

                        tol_eod = (trend_price * Decimal(vibration_point)).quantize(Decimal("0.01"))
                        upper_bnd_eod = trend_price + tol_eod

                        low_i = Decimal(str(row["low"]))
                        if low_i <= upper_bnd_eod:
                            all_above = False
                            break

                    # print(all_above, "all_above")
                    if all_above:
                        touched = True

            # print(current_touched, "TOUCHED")
            # print("___________")
            # store TrendLineCheck entry
            TrendLineCheck.objects.update_or_create(
                trend_line=tl,
                date=today,
                defaults={
                    "line_price": line_price,
                    "actual_price": bar_close,
                    "touched": touched,
                },
            )

            if touched:
                subject = f"Trend Line Touched: {tl.symbol} @ {now.strftime('%d/%m/%Y %I:%M %p')}"
                body = (
                    f"The price bar from {start_ts}–{end_ts} touched your {angle}° line at {line_price}.\n"
                    f"Actual low/high: {bar_low}/{bar_high}.\n"
                    f"Confirmed: Last 10 EOD bars were above trendline (with vibration tolerance)."
                )
                recipients = settings.EMAIL_RECIPIENTS
                send_notification_email(subject, body, recipients)

                print(f"[{now.strftime('%H:%M')}] TrendLine {tl.id} touched at {line_price} (bar {start_ts}–{end_ts})")


class Command(BaseCommand):
    help = "Recompute trend-lines and check every 15 min whether the latest 15m bar touches them."

    def handle(self, *args, **options):
        TrendLineChecker(settings.DATA_DHAN_ACCESS_TOKEN).run()
