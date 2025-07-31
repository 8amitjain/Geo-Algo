from __future__ import annotations

from datetime import timedelta, datetime
from decimal import Decimal

from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.utils import timezone
from requests import HTTPError

from geo_algo import settings

from .dhan import DHANClient, TrendLine as CoreTrendLine


class TrendLine(models.Model):
    symbol = models.CharField(max_length=200, help_text="Ticker symbol, e.g. 'TCS'")
    security_id = models.CharField(max_length=200, help_text="DHAN security ID for the symbol")  # DO not show in list
    start_date = models.DateField(help_text="Date at which the trend line begins")
    angles = ArrayField(
        base_field=models.FloatField(),
        blank=True,
        null=True,
        help_text="List of trend-line angles in degrees (e.g. [45, 65])",
    )
    price_to_bar_ratio = models.DecimalField(max_digits=20, decimal_places=4, help_text="Price-per-bar ratio used to compute the slope")
    start_price = models.DecimalField(max_digits=20, decimal_places=4, help_text="Exact close price on start_date")
    line_data = models.JSONField(blank=True, null=True)  # DO not show in list
    created_at = models.DateTimeField(auto_now_add=True, help_text="When this TrendLine record was created")

    percent_difference_cached = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Cached % difference from latest valid trading day"
    )
    percent_diff_updated_date = models.DateField(
        null=True, blank=True,
        help_text="Date of last update for percent difference"
    )

    class Meta:
        unique_together = ("symbol", "start_date", "angles")
        verbose_name = "Trend Line"
        verbose_name_plural = "Trend Lines"

    def __str__(self):
        # angles_str = ", ".join(str(a) for a in self.angles)
        return f"{self.symbol} @ {self.start_date} → [{self.angles}]°"

    @property
    def is_touched(self) -> bool:
        # True if any related check ever had touched=True
        return self.checks.filter(touched=True).exists()

    @property
    def is_purchased(self) -> bool:
        # True if any related check ever had touched=True
        return self.checks.filter(purchased=True).exists()

    @property
    def percent_difference_from_today(self) -> float | None:
        """Return % difference between actual price and trendline price for the most recent trading day."""
        now = timezone.now()
        client = DHANClient(access_token=settings.DATA_DHAN_ACCESS_TOKEN)

        # Step 1: Get last available intraday bar
        bar_close = None
        trendline_date = None

        for offset in range(0, 5):  # Look back max 5 days
            candidate_day = (now - timedelta(days=offset)).date()
            start_ts = datetime.combine(candidate_day, timezone.datetime.min.time())
            end_ts = datetime.combine(candidate_day, timezone.datetime.max.time())

            try:
                intraday = client.get_intraday_ohlc(
                    security_id=self.security_id,
                    interval=15,
                    start_date=start_ts.strftime("%Y-%m-%d %H:%M:%S"),
                    end_date=end_ts.strftime("%Y-%m-%d %H:%M:%S"),
                )
            except HTTPError as e:
                print(f"HTTP error in intraday fetch: {e}")
                return None
            except Exception as e:
                print(f"General error in intraday fetch: {e}")
                return None

            if not intraday.empty:
                bar_close = Decimal(str(intraday["close"].iat[-1]))
                trendline_date = candidate_day
                break

        if not bar_close or not trendline_date:
            return None

        # Step 2: Get or compute trendline price
        rec = next(
            (pt for pt in (self.line_data or []) if pt["date"] == trendline_date.strftime("%Y-%m-%d")),
            None
        )

        if not rec:
            try:
                full_df = client.get_full_history(self.security_id)
            except HTTPError as e:
                print(f"HTTP error in full_history fetch: {e}")
                return None
            except Exception as e:
                print(f"Error fetching full history: {e}")
                return None

            try:
                core_tl = CoreTrendLine(
                    full_df=full_df,
                    start_date=self.start_date,
                    angle_deg=self.angles[0],
                    price_to_bar_ratio=self.price_to_bar_ratio,
                )
                xs, ys = core_tl.get_points()
                for dt, val in zip(core_tl.dates, ys):
                    if dt.date() == trendline_date:
                        rec = {"date": dt.strftime("%Y-%m-%d"), "value": float(val)}
                        break
            except Exception as e:
                print(f"CoreTrendLine generation failed: {e}")
                return None

        if not rec:
            return None

        try:
            trendline_price = Decimal(str(rec["value"]))
            percent_diff = ((bar_close - trendline_price) / trendline_price) * 100
            return float(round(percent_diff, 2))
        except Exception as e:
            print(f"Failed to compute % diff: {e}")
            return None


# TODO detail button - # http://127.0.0.1:8000/market/ema_crossover_chart?security_id=21808&interval=15&date=2025-05-30
class TrendLineCheck(models.Model):
    trend_line = models.ForeignKey(TrendLine, on_delete=models.CASCADE, related_name="checks", help_text="The TrendLine being evaluated")
    date = models.DateField(help_text="Date for which the line was checked")

    line_price = models.DecimalField(max_digits=20, decimal_places=4, help_text="The trend-line price on this date")
    actual_price = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True, help_text="The actual market close on this date")
    stop_loss_price = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True,  help_text="Stop Loss price sell stock when reached this price")
    buy_above_high_price = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True, help_text="The actual price of cross over candle high")
    purchase_qty = models.IntegerField(null=True, blank=True, help_text="The actual qty bought")

    touched = models.BooleanField(default=False, help_text="Whether the actual price touched the trend line")
    purchased = models.BooleanField(default=False, help_text="Whether the actual price purchased the trend line")
    sold = models.BooleanField(default=False, help_text="Whether the stock was sold")
    cross_over_ema = models.BooleanField(default=False, help_text="Whether the EMA cross over happened")

    checked_at = models.DateTimeField(auto_now_add=True, help_text="When this check was performed")  # TODO REMOVE

    class Meta:
        unique_together = ("trend_line",  "date")
        ordering = ["-date"]

    def __str__(self):
        status = "✔" if self.touched else "✘"
        purchased_status = "✔" if self.purchased else "✘"
        cross_over_ema_status = "✔" if self.cross_over_ema else "✘"
        return f"{self.trend_line} on {self.date}: Touched: {status} - Cross Over EMA: {cross_over_ema_status} - Purchased: {purchased_status}"


