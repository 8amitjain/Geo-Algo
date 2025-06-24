from django.db import models

# TODO - NAV - home - http://127.0.0.1:8000/market/


# TODO Page - Alert set on stocks
# TODO add filter on Touched - FK, exclude - purchased - FK, Search -  symbol, start date created_at.
# TODO detail button - http://127.0.0.1:8000/market/chart.png?symbol=SBI+Life+Insurance&security_id=21808&start_price=low&start_date=2025-03-12&price_to_bar_ratio=4&angles=45,63.251
class TrendLine(models.Model):
    symbol = models.CharField(max_length=20, help_text="Ticker symbol, e.g. 'TCS'")
    security_id = models.CharField(max_length=20, help_text="DHAN security ID for the symbol")  # DO not show in list
    start_date = models.DateField(help_text="Date at which the trend line begins")
    angles = models.JSONField(blank=True, null=True, help_text="List of trend-line angles in degrees (e.g. [45,  65])")
    price_to_bar_ratio = models.FloatField(help_text="Price-per-bar ratio used to compute the slope")
    start_price = models.DecimalField(max_digits=20, decimal_places=4, help_text="Exact close price on start_date")
    line_data = models.JSONField(blank=True, null=True) # DO not show in list
    created_at = models.DateTimeField(auto_now_add=True, help_text="When this TrendLine record was created")

    def __str__(self):
        # angles_str = ", ".join(str(a) for a in self.angles)
        return f"{self.symbol} @ {self.start_date} → [{self.angles}]°"


# TODO page title price touched angle/ trend line
# TODO detail button - # http://127.0.0.1:8000/market/ema_crossover_chart?security_id=21808&interval=15&date=2025-05-30
# TODO FILTERS - date, purchased, checked_at
# TODO QS - touched ==  TRUE & purchased == False
class TrendLineCheck(models.Model):
    trend_line = models.ForeignKey(TrendLine, on_delete=models.CASCADE, related_name="checks", help_text="The TrendLine being evaluated")
    date = models.DateField(help_text="Date for which the line was checked")
    line_price = models.DecimalField(max_digits=20, decimal_places=4, help_text="The trend-line price on this date")
    actual_price = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True, help_text="The actual market close on this date")
    touched = models.BooleanField(default=False, help_text="Whether the actual price touched the trend line")
    purchased = models.BooleanField(default=False, help_text="Whether the actual price purchased the trend line")
    checked_at = models.DateTimeField(auto_now_add=True, help_text="When this check was performed")

    class Meta:
        unique_together = ("trend_line",  "date")
        ordering = ["-date"]

    def __str__(self):
        status = "✔" if self.touched else "✘"
        return f"{self.trend_line} on {self.date}: {status}"


# TODO page - Stocks Purchased
# TODO view - QS - purchased == True, stock name in list
