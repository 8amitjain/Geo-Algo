from django.db import models


class StrategyStock(models.Model):
    """Stocks we are tracking for the strategy."""
    name = models.CharField(max_length=200)  # e.g. "INFY"
    security_id = models.CharField(max_length=200)

    active = models.BooleanField(default=True)

    # Strategy state
    reversal_bar1_date = models.DateField(null=True, blank=True)
    reversal_bar1_high = models.FloatField(null=True, blank=True)
    reversal_bar2_date = models.DateField(null=True, blank=True)
    reversal_bar2_high = models.FloatField(null=True, blank=True)
    reversal_bar_found = models.BooleanField(default=False)
    is_purchased = models.BooleanField(default=False)

    entry_price = models.FloatField(null=True, blank=True)
    stop_loss = models.FloatField(null=True, blank=True)
    tsl_active = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("name", "security_id")

    def __str__(self):
        return f"{self.name} ({self.security_id})"
