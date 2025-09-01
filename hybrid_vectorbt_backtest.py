import pandas as pd
import vectorbt as vbt

# ==============================
# Django setup
# ==============================
import os
import sys

# Absolute path to your project root (where manage.py lives)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

# Point to settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geo_algo.settings")
import django
django.setup()

from market.models import TrendLine  # change 'app' to your Django app name

# ==============================
# Step 1: Load tickers & TrendLine params from DB
# ==============================
trendlines = TrendLine.objects.all()
TICKERS = [t.ticker for t in trendlines]

TRENDLINE_PARAMS = {
    t.ticker: {
        "start_date": str(t.start_date),
        "start_price": float(t.start_price),
        "price_to_bar_ratio": float(t.price_to_bar_ratio),
    }
    for t in trendlines
}
print("Tickers:", TICKERS)
print("Trendline params:", TRENDLINE_PARAMS)

# ==============================
# Step 2: Download market data
# ==============================
# Daily for trendline
close_daily = vbt.YFData.download(TICKERS, interval="1d").get("Close")

# 15m for MA + breakout
data_15m = vbt.YFData.download(TICKERS, interval="15m")
close_15m = data_15m.get("Close")
high_15m = data_15m.get("High")

# ==============================
# Step 3: Trendline function
# ==============================
def generate_trendline_series(price, start_date, start_price, ratio):
    bars_from_start = (price.index - pd.to_datetime(start_date)).days
    line = start_price + (bars_from_start * ratio)
    return pd.Series(line, index=price.index)

# ==============================
# Step 4: Generate entry conditions
# ==============================
entry_trendline = {}
entry_ma = {}
entry_breakout = {}

for ticker in TICKERS:
    # --- Trendline touch (daily) ---
    params = TRENDLINE_PARAMS[ticker]
    trendline = generate_trendline_series(
        close_daily[ticker],
        params["start_date"],
        params["start_price"],
        params["price_to_bar_ratio"],
    )
    trendline_touch = close_daily[ticker] <= trendline

    # --- MA crossover (15m) ---
    ma_fast = close_15m[ticker].rolling(5).mean()
    ma_slow = close_15m[ticker].rolling(25).mean()
    ma_cross = (ma_fast > ma_slow) & (ma_fast.shift(1) <= ma_slow.shift(1))

    # --- Breakout condition (15m, simple version) ---
    breakout = close_15m[ticker] > (high_15m[ticker].shift(1) * 1.01)

    entry_trendline[ticker] = trendline_touch.reindex(close_15m.index, method="ffill")
    entry_ma[ticker] = ma_cross
    entry_breakout[ticker] = breakout

# ==============================
# Step 5: Combine signals
# ==============================
entries = pd.DataFrame({t: entry_trendline[t] & entry_ma[t] & entry_breakout[t] for t in TICKERS})
exits = entries.shift(10).fillna(False)  # example: exit after 10 bars

# ==============================
# Step 6: Backtest
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
portfolio.plot().show()
