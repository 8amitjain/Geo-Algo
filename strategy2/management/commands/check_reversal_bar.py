from django.core.management.base import BaseCommand
from django.utils import timezone

from strategy2.models import StrategyStock
from market.dhan import DHANClient
import math
from django.conf import settings


class Command(BaseCommand):
    help = "Check daily bullish reversal (10-bar logic with R1 lowest low, R2 confirmation, and SL calculation)"

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

            # --- Step 1: Find the lowest candle (R1) ---
            r1_idx = last10["low"].idxmin()
            r1 = last10.loc[r1_idx]

            # --- Step 2: Look ahead up to 4 candles for R2 ---
            r1_position = last10.index.get_loc(r1_idx)
            r2 = None

            for i in range(r1_position + 1, min(r1_position + 5, len(last10))):
                candidate = last10.iloc[i]

                # Condition A: R2 high > R1 high
                if candidate["high"] <= r1["high"]:
                    continue

                # Condition B: R2 low >= R1 low
                if candidate["low"] < r1["low"]:
                    continue

                # ✅ Found valid R2
                r2 = candidate
                break

            if r2 is None:
                # No valid reversal setup
                stock.reversal_bar_found = False
                stock.entry_price = None
                stock.stop_loss = None
                stock.reversal_bar1_high = None
                stock.reversal_bar2_high = None
                stock.reversal_bar1_date = None
                stock.reversal_bar2_date = None
                stock.save()
                self.stdout.write(self.style.WARNING(f"{stock.name} ❌ No valid bullish reversal in last 10 candles"))
                continue

            # --- Step 3: Save setup ---
            stock.reversal_bar_found = True

            # R1 (lowest candle)
            stock.reversal_bar1_high = r1["high"]
            stock.reversal_bar1_date = r1.name.date()

            # R2 (confirmation candle)
            stock.reversal_bar2_high = r2["high"]
            stock.reversal_bar2_date = r2.name.date()

            # Entry = R2 high + buffer
            stock.entry_price = math.ceil(r2["high"] * 1.003) + 0.20

            # Stop Loss = R1 low × 0.9967
            stock.stop_loss = round(r1["low"] * 0.9967, 2)

            stock.save()

            msg = (
                f"{stock.name} ✅ Bullish Reversal Setup | "
                f"R1: {stock.reversal_bar1_date} (Low {r1['low']}, High {r1['high']}) | "
                f"R2: {stock.reversal_bar2_date} (High {r2['high']}) | "
                f"Entry {stock.entry_price} | SL {stock.stop_loss}"
            )
            self.stdout.write(self.style.SUCCESS(msg))
