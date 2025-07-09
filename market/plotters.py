import math
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import List, Union
from .indicators import DEMAIndicator
from pandas.tseries.offsets import BDay


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
        start_date: Union[str, pd.Timestamp],
    ) -> None:
        # 1) ensure timestamp column
        df = df.copy()
        if isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index().rename(columns={"index": "timestamp"})
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        self.df = df
        self.symbol = symbol

        # 2) use the supplied start_bar index
        # 2) locate the start bar by timestamp
        ts = pd.to_datetime(start_date)
        # find the insertion index where timestamp >= ts
        idx = df["timestamp"].searchsorted(ts, side="left")
        if idx >= len(df):
            raise ValueError(f"start_date {start_date!r} is past end of data.")
        self.start_bar = int(idx)
        self.start_ts = df.at[self.start_bar, "timestamp"]
        self.start_price = float(df.at[self.start_bar, start_price_value])

        # 3) parameters for trend-lines
        self.angles = angles
        self.ratio = price_to_bar_ratio

        # 4) last bar index
        self.end_bar = len(df) - 1

    def get_holiday_gaps(self):
        dates = self.df["timestamp"].dt.normalize().drop_duplicates().sort_values()
        holidays = []
        for prev, curr in zip(dates[:-1], dates[1:]):
            delta = (curr - prev).days
            if delta > 1:
                # add all missing days (excluding weekends)
                holidays.extend(
                    pd.date_range(prev + pd.Timedelta(days=1), curr - pd.Timedelta(days=1), freq="B")
                )
        return [d.strftime("%Y-%m-%d") for d in holidays]

    def build_figure(self) -> go.Figure:
        # create a single-panel subplot
        fig = make_subplots(rows=1, cols=1, shared_xaxes=True)
        # Drop rows with missing OHLC data
        df_clean = self.df.dropna(subset=["open", "high", "low", "close"])
        self.df = df_clean
        # self.df["date_str"] = self.df["timestamp"].dt.strftime("%Y-%m-%d")

        print(self.df['timestamp'].tail())
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

        # 2) Trend-lines ────────────────────────────────────────────────
        # 2) Prepare the full list of timestamps (history + 7 business days)
        hist_idx = pd.DatetimeIndex(
            self.df["timestamp"].iloc[self.start_bar: self.end_bar + 1]
        )
        future_idx = pd.bdate_range(
            start=hist_idx[-1] + BDay(1),
            periods=7
        )
        all_dates = hist_idx.union(future_idx)
        future_end_ts = all_dates[-1]  # the 7-days-out timestamp
        hist_dates = self.df["timestamp"].iloc[self.start_bar: self.end_bar + 1].tolist()

        colors = ["blue", "orange", "purple", "teal"]
        for angle, color in zip(self.angles, colors):
            slope = math.tan(math.radians(angle)) * self.ratio

            # compute the price at each offset 0…N
            offsets = list(range(len(all_dates)))
            all_prices = [self.start_price + slope * off for off in offsets]

            # 2a) Straight two-point line (will render perfectly straight with rangebreaks)
            fig.add_trace(
                go.Scatter(
                    x=[self.start_ts, future_end_ts],
                    y=[self.start_price, all_prices[-1]],
                    mode="lines",
                    name=f"{angle}° Trend",
                    line=dict(color=color, width=2),
                ),
                row=1, col=1
            )

            # # 2b) Hover markers at every point
            fig.add_trace(
                go.Scatter(
                    x=all_dates,
                    y=all_prices,
                    mode="markers",
                    name=f"{angle}° points",
                    marker=dict(color=color, size=4),
                    hovertemplate="%{x|%d/%m/%Y}: %{y:.2f}<extra></extra>",
                ),
                row=1, col=1
            )

        # ── 3) Layout & controls ───────────────────────────────────────────
        #

        visible_bars = 75
        price_range = self.ratio * visible_bars

        # Price bounds based on ratio
        ymin = self.start_price - price_range / 2
        ymax = self.start_price + price_range / 2

        # Time bounds and pad for zoom-out
        x_start = self.df["timestamp"].iloc[self.start_bar]
        x_end_idx = min(self.start_bar + visible_bars, len(self.df) - 1)
        x_end = self.df["timestamp"].iloc[x_end_idx]

        x_min = self.df["timestamp"].iloc[0]
        x_max = self.df["timestamp"].iloc[-1]
        x_pad = (x_max - x_min) * 0.5

        fig.update_layout(
            title=f"{self.symbol} — Fully Zoomable Chart with Angle Slope Frame",
            xaxis=dict(
                range=[x_start - x_pad, x_end + x_pad],
                type="date",
                fixedrange=False,
                rangebreaks=[
                    dict(bounds=["sat", "mon"]),
                    dict(values=self.get_holiday_gaps())
                ],
                title="Date",
                autorange=False
            ),
            yaxis=dict(
                range=[ymin - price_range, ymax + price_range],
                fixedrange=False,
                autorange=False,
                title="Price"
            ),
            dragmode="pan",  # ✅ enable pan on both axes
            hovermode="x unified",
            legend=dict(title="Legend"),
            margin=dict(l=50, r=50, t=50, b=50),
        )

        fig.update_layout(
            title=f"{self.symbol} — Candlestick & Angle Trends",
            xaxis=dict(
                title="Date",
                type="date",
                rangeslider=dict(visible=True),
                rangeselector=dict(
                    buttons=[
                        dict(count=7, label="1w", step="day", stepmode="backward"),
                        dict(count=1, label="1m", step="month", stepmode="backward"),
                        dict(count=3, label="3m", step="month", stepmode="backward"),
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
        df_ema = DEMAIndicator.add_emas(self.df, price_col="close")

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
