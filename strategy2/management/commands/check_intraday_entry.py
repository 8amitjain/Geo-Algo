from django.core.management.base import BaseCommand
from django.utils import timezone
from strategy2.models import StrategyStock
from market.dhan import DHANClient
from django.conf import settings
from datetime import datetime, timedelta


class Command(BaseCommand):
    help = "Check intraday 15m entry trigger"

    def handle(self, *args, **options):
        client = DHANClient(access_token=settings.DATA_DHAN_ACCESS_TOKEN)

        today = timezone.now().date() #- timedelta(days=2)
        for stock in StrategyStock.objects.filter(active=True, reversal_bar_high__isnull=False):
            df = client.get_intraday_ohlc(
                stock.security_id,
                start_date=today.strftime("%Y-%m-%d"),
                end_date=today.strftime("%Y-%m-%d"),
                interval=15
            )

            if df.empty:
                continue

            last_candle = df.iloc[-1]
            if last_candle["close"] >= stock.reversal_bar_high:
                # Entry triggered
                stock.tsl_active = True
                stock.stop_loss = None  # will be set by TSL updater
                stock.save()

                self.stdout.write(self.style.SUCCESS(
                    f"Entry Triggered for {stock.name} @ {last_candle['close']}, waiting to place order"
                ))
