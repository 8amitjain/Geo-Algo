import os
import sys
from datetime import timedelta

import pandas as pd
import vectorbt as vbt
import plotly.io as pio
from pandas.tseries.offsets import BDay
from plotly.subplots import make_subplots
import plotly.graph_objects as go
from django.conf import settings

pio.renderers.default = "browser"

# ==============================
# Django setup
# ==============================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geo_algo.settings")
import django
django.setup()

from market.models import TrendLine
from market.plotters import InteractiveChartPlotter, EMACandlestickPlotter
from market.dhan import DHANClient

# ==============================
# Step 1: Load tickers & params from DB
# ==============================
trendlines = list(TrendLine.objects.all()[:2].values(
    "symbol", "security_id", "start_date", "start_price", "price_to_bar_ratio"
))

TICKERS = [t["symbol"] for t in trendlines]

TRENDLINE_PARAMS = {
    t["symbol"]: {
        "security_id": t["security_id"],
        "start_date": str(t["start_date"]),
        "start_price": float(t["start_price"]),
        "price_to_bar_ratio": float(t["price_to_bar_ratio"]),
    }
    for t in trendlines
}

print("Tickers to fetch:", TICKERS)

# ==============================
# Step 2: Download market data from DHAN
# ==============================
dhan = DHANClient(access_token=settings.DATA_DHAN_ACCESS_TOKEN)

# Daily OHLC
daily_data = {}
for ticker, params in TRENDLINE_PARAMS.items():
    security_id = params["security_id"]
    df_daily = dhan.get_full_history(security_id)
    if df_daily.empty:
        print(f"[WARN] No daily data for {ticker}")
        continue
    daily_data[ticker] = df_daily[["open", "high", "low", "close", "volume"]]

# Prepare close_daily for vectorbt
close_daily = pd.DataFrame({t: daily_data[t]["close"] for t in daily_data})
print("Got data for DAILY")

# Intraday 15-min OHLC
close_15m_dict = {}
high_15m_dict = {}

for ticker, params in TRENDLINE_PARAMS.items():
    security_id = params["security_id"]
    df_15m = dhan.get_intraday_ohlc(
        security_id,
        start_date=(pd.Timestamp.today() - timedelta(days=90)).strftime("%Y-%m-%d"),
        end_date=(pd.Timestamp.today() - timedelta(days=2)).strftime("%Y-%m-%d"),  # For weekends
        # end_date=pd.Timestamp.today().strftime("%Y-%m-%d"),  # for weekdays
        interval=15
    )
    if df_15m.empty:
        print(f"[WARN] No 15-min data for {ticker}")
        continue
    close_15m_dict[ticker] = df_15m["close"]
    high_15m_dict[ticker] = df_15m["high"]

close_15m = pd.DataFrame(close_15m_dict)
high_15m = pd.DataFrame(high_15m_dict)

# ==============================
# Step 3: Trendline function
# ==============================
def generate_trendline_series(price: pd.Series, start_date, start_price, price_to_bar_ratio):
    price_index = price.index.tz_localize(None)
    start_date = pd.to_datetime(start_date).tz_localize(None)
    bars_from_start = (price_index - start_date).days
    trendline = start_price + bars_from_start * price_to_bar_ratio
    return pd.Series(trendline, index=price.index)

# ==============================
# Step 4: Entry conditions
# ==============================
entry_trendline = {}
entry_ma = {}
entry_breakout = {}

for ticker in TICKERS:
    if ticker not in close_daily or ticker not in close_15m:
        continue
    params = TRENDLINE_PARAMS[ticker]

    # --- Trendline touch (daily) ---
    trendline = generate_trendline_series(
        close_daily[ticker],
        params["start_date"],
        params["start_price"],
        params["price_to_bar_ratio"],
    )
    trendline_touch_daily = close_daily[ticker] <= trendline
    trendline_touch = trendline_touch_daily.reindex(close_15m.index, method="ffill")

    # --- MA crossover (15m) ---
    ma_fast = close_15m[ticker].rolling(5).mean()
    ma_slow = close_15m[ticker].rolling(25).mean()
    ma_cross = (ma_fast > ma_slow) & (ma_fast.shift(1) <= ma_slow.shift(1))

    # --- Breakout (15m, 1% above prev high) ---
    breakout = close_15m[ticker] > (high_15m[ticker].shift(1) * 1.01)

    entry_trendline[ticker] = trendline_touch
    entry_ma[ticker] = ma_cross
    entry_breakout[ticker] = breakout

entries = pd.DataFrame({t: entry_trendline[t] & entry_ma[t] & entry_breakout[t] for t in TICKERS})
entries = entries.reindex(close_15m.index).fillna(False)
exits = entries.shift(10).fillna(False)

# ==============================
# Step 5: Backtest
# ==============================
portfolio = vbt.Portfolio.from_signals(
    close=close_15m,
    entries=entries,
    exits=exits,
    size=1.0,
    fees=0.001,
    freq="15T"
)

print(portfolio.stats())


for ticker in TICKERS:
    if ticker not in daily_data:
        continue
    print(f"=== Plotting {ticker} ===")
    try:
        daily_df = daily_data[ticker].reset_index().rename(columns={"index": "timestamp"})
        daily_df["timestamp"] = pd.to_datetime(daily_df["timestamp"]).dt.tz_localize(None)

        params = TRENDLINE_PARAMS[ticker]

        # =======================
        # 1) Original Trendline figure
        # =======================
        trend_plotter = InteractiveChartPlotter(
            df=daily_df,
            symbol=ticker,
            angles=params.get("angles", [45]),
            price_to_bar_ratio=params["price_to_bar_ratio"],
            start_price_value="low",
            start_date=pd.to_datetime(params["start_date"])
        )
        trendline_fig = trend_plotter.build_figure()

        # =======================
        # 2) EMA crossover figure (5 over 25) on 15-min data
        # =======================
        df_15m = dhan.get_intraday_ohlc(
            params["security_id"],
            start_date=(pd.Timestamp.today() - timedelta(days=90)).strftime("%Y-%m-%d"),
            end_date=(pd.Timestamp.today() - timedelta(days=2)).strftime("%Y-%m-%d"),
            interval=15
        )

        if df_15m.empty:
            print(f"[WARN] No 15-min data for {ticker}, skipping EMA plot")
            continue

        # Use your EMACandlestickPlotter (this removes gaps & applies EMAs)
        ema_plotter = EMACandlestickPlotter(df=df_15m, symbol=ticker)
        ema_fig = ema_plotter.build_figure()

        # =======================
        # 3) Show both
        # =======================
        trendline_fig.show()
        ema_fig.show()

    # Option B: combine using subplots (optional, may reduce zoom interactivity)
    # fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05,
    #                     subplot_titles=("Trendline", "EMA5/25"))
    # for trace in trendline_fig.data:
    #     fig.add_trace(trace, row=1, col=1)
    # for trace in ema_fig.data:
    #     fig.add_trace(trace, row=2, col=1)
    # fig.update_layout(height=900, width=trendline_fig.layout.width)
    # fig.show()

    except Exception as e:
        print(f"[ERROR] Could not plot {ticker}: {e}")


#
# for ticker in TICKERS:
#     if ticker not in daily_data or ticker not in close_15m:
#         continue
#     print(f"=== Plotting {ticker} ===")
#     try:
#         daily_df = daily_data[ticker].reset_index().rename(columns={"index": "timestamp"})
#
#         params = TRENDLINE_PARAMS[ticker]
#
#         # 1) Trendline figure
#         trend_plotter = InteractiveChartPlotter(
#             df=daily_df,
#             symbol=ticker,
#             angles=params.get("angles", [45]),
#             price_to_bar_ratio=params["price_to_bar_ratio"],
#             start_price_value="low",
#             start_date=pd.to_datetime(params["start_date"])
#         )
#         trendline_fig = trend_plotter.build_figure()
#
#         # Highlight trendline touches
#         trendline_series = generate_trendline_series(
#             daily_df["close"],
#             params["start_date"],
#             params["start_price"],
#             params["price_to_bar_ratio"]
#         )
#         touches = daily_df["close"] <= trendline_series
#         trendline_fig.add_trace(
#             go.Scatter(
#                 x=daily_df.loc[touches, "timestamp"],
#                 y=daily_df.loc[touches, "close"],
#                 mode="markers",
#                 name="Trendline Touch",
#                 marker=dict(color="orange", size=10, symbol="x")
#             )
#         )
#
#         # 2) EMA 15-min figure
#         df_15m = dhan.get_intraday_ohlc(
#             params["security_id"],
#             start_date=(pd.Timestamp.today() - timedelta(days=90)).strftime("%Y-%m-%d"),
#             end_date=(pd.Timestamp.today() - timedelta(days=2)).strftime("%Y-%m-%d"),
#             interval=15
#         )
#         if df_15m.empty:
#             print(f"[WARN] No 15-min data for {ticker}, skipping EMA plot")
#             continue
#         df_15m = ensure_datetime_index(df_15m)
#
#         ema_plotter = EMACandlestickPlotter(df=df_15m, symbol=ticker)
#         ema_fig = ema_plotter.build_figure()
#
#         # Show entry/exit markers
#         ema_fig.add_trace(
#             go.Scatter(
#                 x=entries.index[entries[ticker]],
#                 y=close_15m[ticker][entries[ticker]],
#                 mode="markers",
#                 name="Buy Signal",
#                 marker=dict(color="green", size=8, symbol="triangle-up")
#             )
#         )
#         ema_fig.add_trace(
#             go.Scatter(
#                 x=exits.index[exits[ticker]],
#                 y=close_15m[ticker][exits[ticker]],
#                 mode="markers",
#                 name="Sell Signal",
#                 marker=dict(color="red", size=8, symbol="triangle-down")
#             )
#         )
#
#         # Print PnL history
#         trades = portfolio.trades[ticker]
#         print(f"PnL history for {ticker}:\n", trades.records_readable)
#
#         # Show figures
#         trendline_fig.show()
#         ema_fig.show()
#
#     except Exception as e:
#         print(f"[ERROR] Could not plot {ticker}: {e}")
