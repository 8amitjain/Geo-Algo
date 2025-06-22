import pandas as pd


class EMAIndicator:
    """
    Computes exponential moving averages (EMA) for a given DataFrame.
    Provides EMA(5) and EMA(26) by default.
    """

    @staticmethod
    def add_emas(df: pd.DataFrame, price_col: str = "close") -> pd.DataFrame:
        """
        Given a DataFrame indexed by timestamp (or any index) and with a column
        named `price_col`, returns a new DataFrame with two additional columns:
          - 'EMA5'  : EMA with span = 5
          - 'EMA26' : EMA with span = 26

        The original DataFrame is not modified; a copy with the new columns is returned.

        Example:
            df_with_emas = EMAIndicator.add_emas(df, price_col="close")
        """
        df = df.copy()
        df["EMA5"] = df[price_col].ewm(span=5, adjust=False).mean()
        df["EMA26"] = df[price_col].ewm(span=26, adjust=False).mean()
        return df
