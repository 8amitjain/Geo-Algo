from django.core.management.base import BaseCommand
from django.utils import timezone

from strategy2.models import StrategyStock
from market.dhan import DHANClient
import math
from django.conf import settings


class Command(BaseCommand):
    help = "Check daily Bullish Two-Bar Reversal (require 2 full reversals before marking entry, entry from R2)"

    def handle(self, *args, **options):
        client = DHANClient(access_token=settings.DATA_DHAN_ACCESS_TOKEN)

        for stock in StrategyStock.objects.filter(active=True, reversal_bar_found=False):
            df = client.get_ticker_data(
                stock.security_id,
                (timezone.now() - timezone.timedelta(days=30)).strftime("%Y-%m-%d")
            )

            if df.empty or len(df) < 10:
                continue

            last10 = df.tail(10)
            reversal_bars = []

            # Loop backward through last 10 bars
            for i in range(len(last10) - 2, -1, -1):  # need bearish + bullish
                bar1 = last10.iloc[i]  # bearish candidate
                if bar1["close"] >= bar1["open"]:
                    continue  # not bearish

                # Look ahead up to 4 bars for bullish bar2
                for j in range(i + 1, min(i + 5, len(last10))):
                    bar2 = last10.iloc[j]
                    if bar2["close"] <= bar2["open"]:
                        continue  # not bullish

                    # Conditions
                    if bar2["low"] >= bar1["low"]:
                        continue
                    if bar2["close"] <= bar1["close"]:
                        continue

                    # Bars in between must not close above bar1.close
                    if any(last10.iloc[k]["close"] > bar1["close"] for k in range(i + 1, j)):
                        continue

                    # ✅ Found a valid reversal (bear + bull)
                    reversal_bars.append((bar1, bar2))

                    if len(reversal_bars) == 2:
                        break
                if len(reversal_bars) == 2:
                    break

            # Save only if 2 reversals found
            if len(reversal_bars) == 2:
                stock.reversal_bar_found = True

                # Latest reversal (R1)
                r1_bear, r1_bull = reversal_bars[0]
                stock.reversal_bar1_high = r1_bull["high"]
                stock.reversal_bar1_date = r1_bull.name.date()

                # Second reversal (R2) → used for entry
                r2_bear, r2_bull = reversal_bars[1]
                stock.reversal_bar2_high = r2_bull["high"]
                stock.reversal_bar2_date = r2_bull.name.date()

                # ✅ Entry price based on R2 (older bullish bar)
                stock.entry_price = math.ceil(r2_bull["high"] * 1.003) + 0.20

                stock.save()

                msg = f"{stock.name} ✅ Two-Bar Reversal Confirmed | R1: {stock.reversal_bar1_date} | R2: {stock.reversal_bar2_date} | Entry {stock.entry_price}"
                self.stdout.write(self.style.SUCCESS(msg))

            else:
                # Not enough reversals → clear fields
                stock.reversal_bar_found = False
                stock.entry_price = None
                stock.reversal_bar1_high = None
                stock.reversal_bar2_high = None
                stock.reversal_bar1_date = None
                stock.reversal_bar2_date = None
                stock.save()
                self.stdout.write(self.style.WARNING(f"{stock.name} ❌ Less than 2 reversals found"))
