# market/management/commands/check_trend_lines.py

from decimal import Decimal
from datetime import timedelta, time

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
    bar and marks whether it touched the trend line (±0.5% tolerance).
    """

    def __init__(self, api_token_data: str):
        # only need the history & intraday client
        self.client = DHANClient(access_token=api_token_data)

    def run(self) -> None:
        now = timezone.localtime()

        # 1) Which lines we care about: those that start on/before today,
        #    and for which *today’s* check hasn’t yet been marked touched
        today = now.date()
        to_check = TrendLine.objects.filter(
            start_date__lte=today
        ).exclude(
            # checks__date=today,
            checks__touched=True
        )

        # 2) For each line, recompute its full line_data (so the last price is up-to-date)
        for tl in to_check:
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

            # 3) figure out today’s theoretical line‐price at *this* bar
            #    find the entry in line_data for today (if it exists)
            rec = next(
                (pt for pt in tl.line_data if pt["date"] == today.strftime("%Y-%m-%d")),
                None
            )
            print(rec, "rec")
            if not rec:
                # no price point for today → skip
                continue

            line_price = Decimal(str(rec["value"]))
            print(line_price, "line_price")

            # 4) Fetch the latest 15-minute bar (end = now, start = now-15m)
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

            # assume the *last* row is the most-recent 15m bar
            bar_low = Decimal(str(intraday["low"].iat[-1]))
            bar_high = Decimal(str(intraday["high"].iat[-1]))
            bar_close = Decimal(str(intraday["open"].iat[-1]))
            print(bar_high, bar_low, bar_close)

            # 5) ±0.5% tolerance
            vibration_point = vibration_point_detail()  # TODO add checks if in decimal or throw error over mail
            tol = (line_price * Decimal(vibration_point)).quantize(Decimal("0.0001"))
            lower_bnd = line_price - tol
            upper_bnd = line_price + tol
            print(lower_bnd, upper_bnd)
            # touched = (bar_low <= upper_bnd) or (bar_high >= lower_bnd)
            touched = (bar_high >= lower_bnd) and (bar_low <= upper_bnd)
            print(touched)

            # 6) Record the check for *today*
            TrendLineCheck.objects.update_or_create(
                trend_line=tl,
                date=today,
                defaults={
                    "line_price":   line_price,
                    "actual_price":   bar_close,
                    "touched":      touched,
                },
            )
            if touched:
                subject = f"Trend Line Touched: {tl.symbol} @ {now.strftime('%d/%m/%Y %I:%M %p')}"
                body = (
                    f"The price bar from {start_ts}–{end_ts}"
                    f"touched your {angle}° line at {line_price}.\n"
                    f"Actual low/high: {bar_low}/{bar_high}."
                )
                # replace with whoever should get notified
                recipients = settings.EMAIL_RECIPIENTS
                send_notification_email(subject, body, recipients)

                print(f"[{now.strftime('%H:%M')}] TrendLine {tl.id} touched at {line_price} (bar {start_ts}–{end_ts})")


class Command(BaseCommand):
    help = "Recompute trend-lines and check every 15 min whether the latest 15m bar touches them."

    def handle(self, *args, **options):
        now = timezone.localtime().time()
        print(now)
        # only run during market hours: 09:30 – 15:00 IST
        if not (time(9, 30) <= now <= time(15, 0)):
            return

        checker = TrendLineChecker(
            api_token_data=settings.DATA_DHAN_ACCESS_TOKEN
        )
        checker.run()
        self.stdout.write(self.style.SUCCESS("Trend lines re-computed and checked."))

