# save as hybrid_vectorbt_backtest_with_debug_with_markers.py
import os
import sys
from datetime import timedelta
import math

import pandas as pd
import numpy as np
import vectorbt as vbt
import plotly.io as pio
from plotly.subplots import make_subplots
import plotly.graph_objects as go
from django.conf import settings

pio.renderers.default = "browser"

# Django bootstrap (unchanged)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geo_algo.settings")
import django
django.setup()

from market.models import TrendLine
from market.plotters import InteractiveChartPlotter, EMACandlestickPlotter
from market.dhan import DHANClient

# ----------------- user params -----------------
TOLERANCE_PCT = 0.01   # 0.01% tolerance (adjust if you want tighter/looser)
INTRADAY_LOOKBACK_DAYS = 90
INTRADAY_END_OFFSET_DAYS = 2
EXIT_AFTER_BARS = 10
# ------------------------------------------------


def ensure_datetime_index(df, index_col="timestamp"):
    """Ensure DataFrame has a tz-naive DatetimeIndex."""
    if df is None:
        return pd.DataFrame()
    if not isinstance(df.index, pd.DatetimeIndex):
        if index_col in df.columns:
            df[index_col] = pd.to_datetime(df[index_col])
            df = df.set_index(index_col)
        else:
            try:
                df.index = pd.to_datetime(df.index)
            except Exception as e:
                raise ValueError("No datetime index or timestamp column found") from e
    # make tz-naive
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_convert(None).tz_localize(None)
    return df


def trendline_series_from_daily_df(daily_df, start_date, angle_deg, price_to_bar_ratio, start_price_value="low"):
    """
    Compute trendline values using the exact same logic as InteractiveChartPlotter:
      - find start_bar using searchsorted of start_date on the daily_df['timestamp']
      - start_price = daily_df[start_price_value].iat[start_bar]
      - slope = tan(angle_deg) * price_to_bar_ratio
      - offsets = 0,1,2,... across hist_idx (start_bar..end)
      - produce series indexed by hist_idx timestamps
    Returns: pandas.Series indexed by timestamps (same timestamps as daily_df[start_bar:]).
    """
    df = daily_df.copy().reset_index(drop=True)
    # ensure timestamp column exists in the same format as your plotter expects
    if "timestamp" not in df.columns:
        # maybe df.index is datetime — turn into timestamp column
        if isinstance(daily_df.index, pd.DatetimeIndex):
            df = daily_df.reset_index().rename(columns={"index": "timestamp"})
        else:
            raise ValueError("daily_df must have 'timestamp' column or a DatetimeIndex")

    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
    ts = pd.to_datetime(start_date)
    # find insertion index where timestamp >= start_date
    start_bar = int(df["timestamp"].searchsorted(ts, side="left"))
    if start_bar >= len(df):
        raise ValueError(f"start_date {start_date!r} is past end of daily data (start_bar {start_bar} >= len {len(df)})")

    start_price = float(df.at[start_bar, start_price_value])
    slope = math.tan(math.radians(angle_deg)) * float(price_to_bar_ratio)

    hist_idx = pd.DatetimeIndex(df["timestamp"].iloc[start_bar: len(df)])
    offsets = np.arange(len(hist_idx))
    prices = start_price + offsets * slope

    return pd.Series(prices, index=hist_idx)


def get_holiday_gaps_from_index(ts_index):
    """Utility to return business-day gap dates for Plotly rangebreak 'values' list"""
    dates = pd.to_datetime(ts_index).normalize().drop_duplicates().sort_values()
    gaps = []
    for prev, curr in zip(dates[:-1], dates[1:]):
        delta = (curr - prev).days
        if delta > 1:
            gaps.extend(pd.date_range(prev + pd.Timedelta(days=1), curr - pd.Timedelta(days=1), freq="B"))
    return [d.strftime("%Y-%m-%d") for d in gaps]


# -------------------- Main --------------------
trendlines_qs = list(TrendLine.objects.all()[:5].values(
    "symbol", "security_id", "start_date", "start_price", "price_to_bar_ratio", "angles"
))
if not trendlines_qs:
    raise SystemExit("No TrendLine records found in DB")

TRENDLINE_PARAMS = {}
TICKERS = []
for t in trendlines_qs:
    sym = t["symbol"]
    TICKERS.append(sym)
    TRENDLINE_PARAMS[sym] = {
        "security_id": t["security_id"],
        "start_date": str(t["start_date"]),
        "start_price": float(t["start_price"]),
        "price_to_bar_ratio": float(t["price_to_bar_ratio"]),
        "angles": t.get("angles") or [45],
    }

print("Tickers to fetch:", TICKERS)

dhan = DHANClient(access_token=settings.DATA_DHAN_ACCESS_TOKEN)

# download daily data
daily_data = {}
for ticker, params in TRENDLINE_PARAMS.items():
    secid = params["security_id"]
    df_daily = dhan.get_full_history(secid)
    if df_daily is None or df_daily.empty:
        print(f"[WARN] No daily data for {ticker}")
        continue
    df_daily = df_daily.loc[:, ["open","high","low","close","volume"]].copy()
    df_daily = ensure_datetime_index(df_daily)
    daily_data[ticker] = df_daily

if not daily_data:
    raise SystemExit("No daily data fetched for any ticker")

# download intraday 15m
intraday_dfs = {}
close_15m_dict = {}
high_15m_dict = {}
for ticker, params in TRENDLINE_PARAMS.items():
    secid = params["security_id"]
    df_15m = dhan.get_intraday_ohlc(
        secid,
        start_date=(pd.Timestamp.today() - timedelta(days=INTRADAY_LOOKBACK_DAYS)).strftime("%Y-%m-%d"),
        end_date=(pd.Timestamp.today() - timedelta(days=INTRADAY_END_OFFSET_DAYS)).strftime("%Y-%m-%d"),
        interval=15
    )
    if df_15m is None or df_15m.empty:
        print(f"[WARN] No intraday data for {ticker}")
        continue
    df_15m = df_15m.loc[:, ["open","high","low","close","volume"]].copy()
    df_15m = ensure_datetime_index(df_15m)
    intraday_dfs[ticker] = df_15m
    close_15m_dict[ticker] = df_15m["close"]
    high_15m_dict[ticker] = df_15m["high"]

if not close_15m_dict:
    raise SystemExit("No intraday data fetched for any ticker")

close_15m = pd.DataFrame(close_15m_dict).sort_index()
high_15m = pd.DataFrame(high_15m_dict).sort_index()
master_idx = close_15m.index

# Build signals (same as you had)
entry_trendline = {}
entry_ma = {}
entry_breakout = {}

for ticker in TICKERS:
    if ticker not in daily_data or ticker not in intraday_dfs:
        print(f"[WARN] {ticker} missing daily or intraday data — skipping signals")
        continue
    params = TRENDLINE_PARAMS[ticker]

    # daily trendline values (per-angle) -> we'll aggregate later but for signals we can use first angle
    angle0 = params.get("angles", [45])[0]
    trendline_daily_vals = trendline_series_from_daily_df(
        daily_data[ticker].reset_index().rename(columns={"index":"timestamp"}),
        params["start_date"],
        angle0,
        params["price_to_bar_ratio"],
        start_price_value="low"
    )
    trendline_intraday_vals = trendline_daily_vals.reindex(master_idx, method="ffill").fillna(method="ffill")

    # touch boolean based on intraday candle containing the trendline value (with tolerance)
    tol_abs = (trendline_intraday_vals.abs() * TOLERANCE_PCT).fillna(0.0)
    s_low = intraday_dfs[ticker]["low"].reindex(master_idx).fillna(method="ffill").fillna(method="bfill")
    s_high = intraday_dfs[ticker]["high"].reindex(master_idx).fillna(method="ffill").fillna(method="bfill")

    trend_touch_mask = (trendline_intraday_vals >= (s_low - tol_abs)) & (trendline_intraday_vals <= (s_high + tol_abs))
    trend_touch_mask = trend_touch_mask.fillna(False).astype(bool)

    # MA crossover
    s_close = close_15m[ticker].reindex(master_idx)
    ma_fast = s_close.rolling(5, min_periods=1).mean()
    ma_slow = s_close.rolling(25, min_periods=1).mean()
    ma_fast_al, ma_slow_al = ma_fast.align(ma_slow, join="inner")
    ma_cross_inner = (ma_fast_al > ma_slow_al) & (ma_fast_al.shift(1) <= ma_slow_al.shift(1))
    ma_cross = ma_cross_inner.reindex(master_idx).fillna(False).astype(bool)

    # breakout
    s_high_all = high_15m[ticker].reindex(master_idx)
    breakout = (s_close > (s_high_all.shift(1) * 1.01)).fillna(False).astype(bool)

    entry_trendline[ticker] = trend_touch_mask
    entry_ma[ticker] = ma_cross
    entry_breakout[ticker] = breakout

# Combine entries
entries = pd.DataFrame(index=master_idx)
for t in entry_trendline.keys():
    entries[t] = entry_trendline[t].reindex(master_idx).fillna(False).astype(bool) & \
                 entry_ma[t].reindex(master_idx).fillna(False).astype(bool) & \
                 entry_breakout[t].reindex(master_idx).fillna(False).astype(bool)

exits = entries.shift(EXIT_AFTER_BARS).reindex(master_idx).fillna(False).astype(bool)

# Backtest
portfolio = vbt.Portfolio.from_signals(
    close=close_15m,
    entries=entries,
    exits=exits,
    size=1.0,
    fees=0.001,
    freq="15T"
)
print("Backtest stats:")
print(portfolio.stats())

# Plotting: daily trendline figure + intraday EMA/trade figure with touches debug and markers
for ticker in TICKERS:
    if ticker not in daily_data or ticker not in intraday_dfs:
        print(f"[WARN] skipping plotting for {ticker}")
        continue
    print(f"=== Plotting {ticker} ===")
    try:
        params = TRENDLINE_PARAMS[ticker]
        # prepare daily_df for plotter
        daily_df = daily_data[ticker].reset_index().rename(columns={"index": "timestamp"})
        daily_df["timestamp"] = pd.to_datetime(daily_df["timestamp"]).dt.tz_localize(None)

        # build trendline figure with existing plotter
        trend_plotter = InteractiveChartPlotter(
            df=daily_df,
            symbol=ticker,
            angles=params.get("angles", [45]),
            price_to_bar_ratio=params["price_to_bar_ratio"],
            start_price_value="low",
            start_date=pd.to_datetime(params["start_date"])
        )
        trendline_fig = trend_plotter.build_figure()

        # For debugging: compute trendline(s) using exact plotter logic per angle
        colors = ["orange", "purple", "teal", "blue", "magenta"]
        for i, angle in enumerate(params.get("angles", [45])):
            tl_series = trendline_series_from_daily_df(
                daily_df,
                params["start_date"],
                angle,
                params["price_to_bar_ratio"],
                start_price_value="low"
            )
            # daily touches: when trendline value lies within daily candle's [low - tol, high + tol]
            tol_abs_daily = (tl_series.abs() * TOLERANCE_PCT).fillna(0.0)
            low_series = daily_data[ticker]["low"].reindex(tl_series.index)
            high_series = daily_data[ticker]["high"].reindex(tl_series.index)
            touches_mask_daily = (tl_series >= (low_series - tol_abs_daily)) & (tl_series <= (high_series + tol_abs_daily))
            touches_mask_daily = touches_mask_daily.fillna(False).astype(bool)

            # Align mask to daily_data[ticker] index (fixes unalignable boolean error)
            aligned_mask = touches_mask_daily.reindex(daily_data[ticker].index, fill_value=False)

            touches_df_daily = daily_data[ticker].loc[aligned_mask]
            # add trendline_value column for debugging
            if not touches_df_daily.empty:
                tl_vals_for_rows = tl_series.reindex(touches_df_daily.index)
                touches_df_daily = touches_df_daily.copy()
                touches_df_daily["trendline_value"] = tl_vals_for_rows.values
                touches_df_daily["pct_dist"] = ((touches_df_daily["close"] - touches_df_daily["trendline_value"]) / touches_df_daily["trendline_value"]).abs()

                # console debug
                print(f"\n[DEBUG] {ticker} daily touches for angle {angle}° (tol {TOLERANCE_PCT*100:.6f}%):")
                print(touches_df_daily[["low","high","close","trendline_value","pct_dist"]].round(6).to_string())

                # add markers at the trendline_value on the daily chart so you can see exact plotted value
                trendline_fig.add_trace(go.Scatter(
                    x=tl_vals_for_rows.index,
                    y=tl_vals_for_rows.values,
                    mode="markers+text",
                    name=f"Touch {angle}°",
                    textposition="top center",
                    marker=dict(color=colors[i % len(colors)], size=9, symbol="x")
                ))

            # Also compute intraday mapping & debug few points (so you see why intraday false positives happened)
            tl_intraday = tl_series.reindex(master_idx, method="ffill")
            # intraday tolerance (absolute)
            tol_intraday_abs = (tl_intraday.abs() * TOLERANCE_PCT).fillna(0.0)
            s_low = intraday_dfs[ticker]["low"].reindex(master_idx).fillna(method="ffill").fillna(method="bfill")
            s_high = intraday_dfs[ticker]["high"].reindex(master_idx).fillna(method="ffill").fillna(method="bfill")
            intraday_touches_mask = (tl_intraday >= (s_low - tol_intraday_abs)) & (tl_intraday <= (s_high + tol_intraday_abs))
            intraday_touches_mask = intraday_touches_mask.fillna(False).astype(bool)

            if intraday_touches_mask.any():
                intraday_touch_times = intraday_touches_mask.index[intraday_touches_mask]
                intraday_debug_df = pd.DataFrame({
                    "timestamp": intraday_touch_times,
                    "low": s_low.reindex(intraday_touch_times).values,
                    "high": s_high.reindex(intraday_touch_times).values,
                    "close": close_15m[ticker].reindex(intraday_touch_times).values,
                    "trendline_value": tl_intraday.reindex(intraday_touch_times).values
                }).set_index("timestamp")
                intraday_debug_df["pct_dist"] = ((intraday_debug_df["close"] - intraday_debug_df["trendline_value"]).abs() / intraday_debug_df["trendline_value"]).replace([np.inf, -np.inf], np.nan)
                print(f"\n[DEBUG] {ticker} intraday touches for angle {angle}° (showing up to 10):")
                print(intraday_debug_df.head(10).round(6).to_string())

        # Build intraday EMA+trades combined figure (uses your EMACandlestickPlotter)
        df_15m = intraday_dfs[ticker].copy()
        # compute EMAs locally (ensure visible lines)
        df_15m["EMA5"] = df_15m["close"].ewm(span=5, min_periods=5).mean()
        df_15m["EMA25"] = df_15m["close"].ewm(span=25, min_periods=25).mean()

        # Use your EMA plotter to get consistent rangebreaks / layout, then add our traces
        ema_plotter = EMACandlestickPlotter(df=df_15m, symbol=ticker)
        ema_fig = ema_plotter.build_figure()

        # Ensure EMA traces exist (if EMACandlestickPlotter already added them, this will duplicate; safe to add again)
        ema_fig.add_trace(go.Scatter(x=df_15m.index, y=df_15m["EMA5"], mode="lines", name="EMA5", line=dict(width=2, color="red")))
        ema_fig.add_trace(go.Scatter(x=df_15m.index, y=df_15m["EMA25"], mode="lines", name="EMA25", line=dict(width=2, color="#FDDA0D")))

        # Add MA-cross markers (use entry_ma mask computed earlier)
        ma_mask = entry_ma.get(ticker)
        if ma_mask is not None:
            ma_mask = ma_mask.reindex(df_15m.index).fillna(False).astype(bool)
            if ma_mask.any():
                ma_times = ma_mask.index[ma_mask]
                ema_fig.add_trace(go.Scatter(
                    x=ma_times,
                    y=df_15m["close"].reindex(ma_times),
                    mode="markers",
                    name="MA Cross",
                    marker=dict(symbol="diamond", color="blue", size=9)
                ))

        # Add breakout markers (use entry_breakout mask computed earlier)
        br_mask = entry_breakout.get(ticker)
        if br_mask is not None:
            br_mask = br_mask.reindex(df_15m.index).fillna(False).astype(bool)
            if br_mask.any():
                br_times = br_mask.index[br_mask]
                ema_fig.add_trace(go.Scatter(
                    x=br_times,
                    y=df_15m["close"].reindex(br_times),
                    mode="markers",
                    name="Breakout",
                    marker=dict(symbol="star", color="orange", size=10)
                ))

        # Add buy / sell markers (entries & exits)
        buy_times = entries.index[entries[ticker]]
        sell_times = exits.index[exits[ticker]]
        buy_times_plot = buy_times.intersection(df_15m.index)
        sell_times_plot = sell_times.intersection(df_15m.index)

        if len(buy_times_plot) > 0:
            ema_fig.add_trace(go.Scatter(
                x=buy_times_plot,
                y=df_15m["close"].reindex(buy_times_plot),
                mode="markers+text",
                name="Buy",
                marker=dict(symbol="triangle-up", color="green", size=10),
                text=["BUY"] * len(buy_times_plot),
                textposition="bottom center"
            ))

        if len(sell_times_plot) > 0:
            ema_fig.add_trace(go.Scatter(
                x=sell_times_plot,
                y=df_15m["close"].reindex(sell_times_plot),
                mode="markers+text",
                name="Sell",
                marker=dict(symbol="triangle-down", color="red", size=10),
                text=["SELL"] * len(sell_times_plot),
                textposition="top center"
            ))

        # Also plot intraday trendline mapping for the first angle for visual cross-check
        angle0 = params.get("angles", [45])[0]
        tl_series_hist = trendline_series_from_daily_df(
            daily_df,
            params["start_date"],
            angle0,
            params["price_to_bar_ratio"],
            start_price_value="low"
        )
        tl_intraday_map = tl_series_hist.reindex(df_15m.index, method="ffill")
        ema_fig.add_trace(go.Scatter(
            x=df_15m.index,
            y=tl_intraday_map,
            mode="lines",
            name=f"Trendline {angle0}° (mapped)",
            line=dict(color="orange", width=1, dash="dash")
        ))

        # Print PnL / trades for debugging
        try:
            trades_obj = portfolio.trades[ticker]
            trades_table = getattr(trades_obj, "records_readable", None) or getattr(trades_obj, "records", None)
            print(f"\nTrades for {ticker} (readable):\n", trades_table)
        except Exception:
            print(f"No trade records for {ticker}")

        # Show both figures (separate windows)
        trendline_fig.show()
        ema_fig.show()

    except Exception as e:
        print(f"[ERROR] Could not plot {ticker}: {e}")
