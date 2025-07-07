import pandas as pd
from variables.models import DEMASetting


class DEMAIndicator:
    @staticmethod
    def dema(series: pd.Series, span: int) -> pd.Series:
        """
        Double Exponential Moving Average:
          DEMA = 2 * EMA(span) - EMA_of_EMA(span)
        """
        ema1 = series.ewm(span=span, adjust=False).mean()
        ema2 = ema1.ewm(span=span, adjust=False).mean()
        return 2 * ema1 - ema2

    @staticmethod
    def add_demas(df: pd.DataFrame, price_col: str = "close") -> pd.DataFrame:
        """
        Reads all EMASetting objects and adds DEMA columns for each span‐pair.
        """

        out = df.copy()
        for setting in DEMASetting.objects.all():
            f, s = setting.fast_span, setting.slow_span
            out[f"DEMA{f}"] = DEMAIndicator.dema(out[price_col], span=f)
            out[f"DEMA{s}"] = DEMAIndicator.dema(out[price_col], span=s)
        return out
