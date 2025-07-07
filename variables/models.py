from django.db import models


class VibrationPoint(models.Model):
    vibration_point_value = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="% buffer/allowance for buy signals"
    )
    last_modified = models.DateTimeField(
        auto_now=True,
        help_text="When this value was last updated"
    )

    def __str__(self):
        return f"{self.vibration_point_value}%"


class DEMASetting(models.Model):
    """
    Defines one pair of spans for a Double-EMA crossover check.
    """
    fast_span = models.PositiveIntegerField(help_text="Fast DEMA span (e.g. 5)")
    slow_span = models.PositiveIntegerField(help_text="Slow DEMA span (e.g. 26)")
    last_modified = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("fast_span", "slow_span")
        ordering = ["fast_span"]

    def __str__(self):
        return f"DEMA {self.fast_span}/{self.slow_span}"