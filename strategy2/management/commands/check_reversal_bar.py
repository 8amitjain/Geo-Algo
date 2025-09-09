from django.core.management.base import BaseCommand
from django.utils import timezone

from strategy2.models import StrategyStock
from market.dhan import DHANClient
import math
import pandas as pd
from django.conf import settings


class Command(BaseCommand):
    help = "Check daily reversal bar setup"

    def handle(self, *args, **options):
        client = DHANClient(access_token=settings.DATA_DHAN_ACCESS_TOKEN)

        for stock in StrategyStock.objects.filter(active=True):
            df = client.get_ticker_data(stock.security_id, (timezone.now() - timezone.timedelta(days=30)).strftime("%Y-%m-%d"))

            if df.empty or len(df) < 10:
                continue

            last10 = df.tail(10)

            # reversal bar = bullish engulfing OR other logic?
            reversal_bar = None
            for i in range(len(last10) - 1, -1, -1):
                candle = last10.iloc[i]
                # Example condition: bullish close after 4 or fewer candles gap
                if candle["close"] > candle["open"]:
                    gap = (len(last10) - 1) - i
                    if gap <= 4:
                        reversal_bar = candle
                        break

            if reversal_bar is not None:
                high = reversal_bar["high"]
                entry_price = math.ceil(high * 1.003) + 0.20

                stock.reversal_bar_high = high
                stock.reversal_bar_date = reversal_bar.name.date()
                stock.entry_price = entry_price
                stock.save()

                self.stdout.write(self.style.SUCCESS(
                    f"{stock.name} reversal bar set @ {reversal_bar.name.date()} | Entry {entry_price}"
                ))
