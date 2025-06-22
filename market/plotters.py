# market/plotters.py

import math
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import List, Union
from .indicators import EMAIndicator


class InteractiveChartPlotter:
    """
    Builds a Plotly Figure with:
      - OHLC candlesticks (from a `timestamp` column)
      - True-angle trend lines at given angles (solid, forward-only)
      - Full zoom/pan/range-slider controls
    """

    def __init__(
        self,
        df: pd.DataFrame,
        symbol: str,
        angles: List[float],
        price_to_bar_ratio: float,
        start_price_value: str,
        start_bar: int
    ) -> None:
        # 1) ensure timestamp column
        df = df.copy()
        if isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index().rename(columns={"index": "timestamp"})
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        self.df = df
        self.symbol = symbol

        # 2) use the supplied start_bar index
        if not (0 <= start_bar < len(df)):
            raise ValueError(f"start_bar {start_bar} out of range [0, {len(df)-1}]")
        self.start_bar = start_bar
        self.start_ts = df.loc[start_bar, "timestamp"]
        # pick the column (e.g. "low" or "close") for the starting price
        self.start_price = float(df.loc[start_bar, start_price_value])

        # 3) parameters for trend-lines
        self.angles = angles
        self.ratio = price_to_bar_ratio

        # 4) last bar index
        self.end_bar = len(df) - 1

    def build_figure(self) -> go.Figure:
        # create a single-panel subplot
        fig = make_subplots(rows=1, cols=1, shared_xaxes=True)

        # ── 1) Candlesticks ────────────────────────────────────────────────
        fig.add_trace(
            go.Candlestick(
                x=self.df["timestamp"],
                open=self.df["open"].tolist(),
                high=self.df["high"].tolist(),
                low=self.df["low"].tolist(),
                close=self.df["close"].tolist(),
                name="OHLC",
                increasing_line_color="green",
                decreasing_line_color="red",
                showlegend=True,
            ),
            row=1, col=1
        )

        # ── 2) Trend-lines ────────────────────────────────────────────────
        end_ts = self.df["timestamp"].iat[self.end_bar]
        total_bars = self.end_bar - self.start_bar

        colors = ["blue", "orange", "purple", "teal"]
        for angle, color in zip(self.angles, colors):
            slope = math.tan(math.radians(angle)) * self.ratio
            end_price = self.start_price + slope * total_bars

            fig.add_trace(
                go.Scatter(
                    x=[self.start_ts, end_ts],
                    y=[self.start_price, end_price],
                    mode="lines",
                    name=f"{angle}° Trend",
                    line=dict(color=color, width=2, dash="solid"),
                    showlegend=True,
                ),
                row=1, col=1,
            )

        # ── 3) Layout & controls ───────────────────────────────────────────
        fig.update_layout(
            title=f"{self.symbol} — Candlestick & Angle Trends",
            xaxis=dict(
                title="Date",
                type="date",
                rangeslider=dict(visible=True),
                rangeselector=dict(
                    buttons=[
                        dict(count=7,  label="1w", step="day",   stepmode="backward"),
                        dict(count=1,  label="1m", step="month", stepmode="backward"),
                        dict(count=3,  label="3m", step="month", stepmode="backward"),
                        dict(step="all"),
                    ]
                ),
            ),
            yaxis=dict(title="Price"),
            hovermode="x unified",
            legend=dict(title="Legend"),
            margin=dict(l=50, r=50, t=50, b=50),
        )

        return fig


class EMACandlestickPlotter:
    """
    Builds a Plotly Figure containing:
      - OHLC candlesticks (using the DataFrame’s DateTimeIndex)
      - EMA(5) starting at bar 5
      - EMA(26) starting at bar 26
      - Hides non-trading hours and weekends so days appear contiguous
      - Full zoom/pan/range-slider controls
    """

    def __init__(self, df: pd.DataFrame, symbol: str) -> None:
        """
        Expects df to have either:
          • a DateTimeIndex, or
          • a column named 'timestamp' with datetime-like values.
        Required columns: ['open', 'high', 'low', 'close', 'volume'].
        """
        df = df.copy()
        # if "timestamp" in df.columns:
        #     df["timestamp"] = pd.to_datetime(df["timestamp"])
        #     df.set_index("timestamp", inplace=True)
        if isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index().rename(columns={"index": "timestamp"})
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        elif not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError("DataFrame must have a DateTimeIndex or a 'timestamp' column.")
        df.sort_index(inplace=True)

        self.df = df
        self.symbol = symbol

    def build_figure(self) -> go.Figure:
        # 1) Compute EMAs
        df_ema = EMAIndicator.add_emas(self.df, price_col="close")

        # 2) Create subplot
        fig = make_subplots(rows=1, cols=1, shared_xaxes=True)

        # 3) Add candlestick trace (covers all bars)
        fig.add_trace(
            go.Candlestick(
                x=df_ema["timestamp"],
                open=df_ema["open"].tolist(),
                high=df_ema["high"].tolist(),
                low=df_ema["low"].tolist(),
                close=df_ema["close"].tolist(),
                name="OHLC",
                increasing_line_color="green",
                decreasing_line_color="red",
                showlegend=False,
            ),
            row=1,
            col=1
        )

        # 4) Plot EMA(5) only where it is not NaN (i.e. from the 5th bar onward)

        fig.add_trace(
            go.Scatter(
                x=df_ema["timestamp"],
                y=df_ema["EMA5"].tolist(),
                mode="lines",
                name="EMA(5)",
                line=dict(color="blue", width=1.5),
            ),
            row=1,
            col=1
        )

        # 5) Plot EMA(26) only where it is not NaN (i.e. from the 26th bar onward)

        fig.add_trace(
            go.Scatter(
                x=df_ema["timestamp"],
                y=df_ema["EMA26"].tolist(),
                mode="lines",
                name="EMA(26)",
                line=dict(color="orange", width=1.5),
            ),
            row=1,
            col=1
        )

        # 6) Hide non-trading hours and weekends
        fig.update_xaxes(
            rangebreaks=[
                dict(bounds=["sat", "mon"]),            # hide weekends
                dict(bounds=[16, 9.5], pattern="hour"),  # hide hours outside 09:30–16:00 IST
            ]
        )

        # 7) Layout & interactive controls
        fig.update_layout(
            title=f"{self.symbol} — Intraday Candlestick + EMA(5/26)",
            xaxis=dict(
                title="Date/Time",
                type="date",
                rangeslider=dict(visible=True),
                rangeselector=dict(
                    buttons=[
                        dict(count=7,  label="1w",  step="day",   stepmode="backward"),
                        dict(count=1,  label="1m",  step="month", stepmode="backward"),
                        dict(count=3,  label="3m",  step="month", stepmode="backward"),
                        dict(step="all"),
                    ]
                ),
            ),
            yaxis=dict(title="Price"),
            hovermode="x unified",
            legend=dict(title="Indicators", orientation="h", y=1.02),
            margin=dict(l=50, r=50, t=60, b=50),
        )

        return fig
