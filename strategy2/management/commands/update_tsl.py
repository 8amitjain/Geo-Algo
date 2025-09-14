from django.core.management.base import BaseCommand
from strategy2.models import StrategyStock
from market.dhan import DHANClient
from django.conf import settings


class Command(BaseCommand):
    help = "Update Trailing Stop Loss (TSL)"

    def handle(self, *args, **options):
        client = DHANClient(access_token=settings.DATA_DHAN_ACCESS_TOKEN)

        for stock in StrategyStock.objects.filter(active=True, reversal_bar_found=True):
            df = client.get_ticker_data(stock.security_id, "2024-01-01")

            last10 = df.tail(10)
            swing_lows = last10["low"].sort_values().tolist()

            if not swing_lows:
                continue

            # lowest low (L1, L2, L3 tracking can be done by saving in DB if needed)
            new_sl = min(swing_lows[-3:]) * 0.9967

            if not stock.stop_loss or new_sl > stock.stop_loss:
                stock.stop_loss = new_sl
                stock.save()
                self.stdout.write(self.style.SUCCESS(
                    f"{stock.name} TSL updated to {stock.stop_loss}"
                ))
