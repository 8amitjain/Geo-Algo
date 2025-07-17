import pandas as pd
from variables.models import EMASetting


class EMAIndicator:
    @staticmethod
    def ema(series: pd.Series, span: int) -> pd.Series:
        return series.ewm(span=span, adjust=False).mean()

    @staticmethod
    def add_emas(df: pd.DataFrame, price_col: str = "close") -> pd.DataFrame:
        out = df.copy()
        for span in [5, 25]:
            out[f"EMA{span}"] = EMAIndicator.ema(out[price_col], span=span)
        return out

    # def add_emas(df: pd.DataFrame, price_col: str = "close") -> pd.DataFrame:
    #     """
    #     Reads all EMASetting objects and adds DEMA columns for each span‐pair.
    #     """
    #
    #     out = df.copy()
    #     for setting in EMASetting.objects.all():
    #         f, s = setting.fast_span, setting.slow_span
    #         out[f"EMA{f}"] = EMAIndicator.ema(out[price_col], span=f)
    #         out[f"EMA{s}"] = EMAIndicator.ema(out[price_col], span=s)
    #     return out
