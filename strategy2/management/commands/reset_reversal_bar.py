from django.core.management.base import BaseCommand
from django.utils import timezone

from strategy2.models import StrategyStock
from market.dhan import DHANClient
import math
from django.conf import settings


class Command(BaseCommand):
    def handle(self, *args, **options):

        for stock in StrategyStock.objects.all():
            stock.reversal_bar_found = False
            stock.entry_price = None
            stock.reversal_bar1_high = None
            stock.reversal_bar2_high = None
            stock.reversal_bar1_date = None
            stock.reversal_bar2_date = None
            stock.save()
