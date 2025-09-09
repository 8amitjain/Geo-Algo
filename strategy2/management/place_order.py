from django.core.management.base import BaseCommand
from market.models import StrategyStock
from dhan import DHANClient
from django.conf import settings


class Command(BaseCommand):
    help = "Place order when entry condition met"

    def handle(self, *args, **options):
        client = DHANClient(access_token=settings.DATA_DHAN_ACCESS_TOKEN)

        for stock in StrategyStock.objects.filter(active=True, tsl_active=True, entry_price__isnull=False):
            # Example: Buy 1 share
            try:
                res = client.place_order(
                    dhan_client_id="YOUR_DHAN_ID",
                    security_id=stock.security_id,
                    transaction_type="BUY",
                    quantity=1,
                    price=stock.entry_price
                )
                self.stdout.write(self.style.SUCCESS(
                    f"Order placed for {stock.name}: {res}"
                ))
            except Exception as e:
                self.stderr.write(f"Order failed for {stock.name}: {e}")
