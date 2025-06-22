from geo_algo import settings
from .plotters import InteractiveChartPlotter, EMACandlestickPlotter
from .services import TrendLinePersistenceService
from .dhan import DHANClient
from .indicators import EMAIndicator
from matplotlib.dates import DateFormatter, MinuteLocator

import io
from datetime import datetime, timedelta
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.dates import DateFormatter, DayLocator
from mplfinance.original_flavor import candlestick_ohlc
from django.http import HttpResponse
from django.shortcuts import render

matplotlib.use("Agg")


"""
Flow in action
User visits /market/ → sees the form.

Submits with e.g. ?symbol=TCS&start_price=3450&start_bar_index=30&price_to_bar_ratio=1&angles=45,65

Django calls stock_chart, generates a PNG on-the-fly, and the <img> tag displays it in the same page.

This keeps your DHAN logic DRY (you’re re-using the same client/plotter classes), and all secrets stay in .env.
"""
# http://127.0.0.1:8000/market/chart.png?symbol=SBI+Life+Insurance&security_id=21808&start_price=low&start_date=2025-03-12&price_to_bar_ratio=4&angles=45,63.251&start_bar=1846


def stock_form(request):
    client = DHANClient(settings.DATA_DHAN_ACCESS_TOKEN)
    resp = client.get_symbols()
    if resp['status_code'] != 200:
        return render(request, 'market/error.html', resp)
    return render(request, 'market/stock_form.html', {'instrument_list': resp['instrument_list']})


def stock_chart(request):
    symbol = request.GET.get('symbol', 'TCS')
    start_price = request.GET.get('start_price', 'low')
    security_id = request.GET.get('security_id')
    start_date = request.GET.get('start_date')
    start_bar = int(request.GET.get('start_bar'))
    ratio = int(request.GET.get('price_to_bar_ratio', 1))
    angles = [float(a) for a in request.GET.get('angles', '45,65').split(',')]

    client = DHANClient(settings.DATA_DHAN_ACCESS_TOKEN)
    df = client.get_full_history(security_id)

    # df = client.get_ticker_data(security_id, start_date)
    # print(df, "df")
    plotter = InteractiveChartPlotter(df, symbol, angles, ratio, start_price, start_bar + 1)
    fig = plotter.build_figure()
    chart_json = fig.to_json()

    # Save data in a model
    persistor = TrendLinePersistenceService(
        df=df,
        symbol=symbol,
        security_id=security_id,
        start_date=start_date,
        price_to_bar_ratio=ratio,
        angles=angles,
    )
    persistor.persist()

    # TODO Create a cron for EMA cross over checks and angle line touch check every 15 mins - double check all logics.
    # BUY call

    return render(request, "market/stock_chart.html", {
            "chart_json": chart_json,
            "symbol": symbol,
        })


# http://127.0.0.1:8000/market/ema_crossover_chart?security_id=21808&interval=15&date=2025-05-30
def candlestick_chart(request):
    symbol = request.GET.get("symbol", "TCS")
    security_id = request.GET.get("security_id")
    start_date = request.GET.get("start_date", "2025-06-02")
    interval = int(request.GET.get("interval", "15"))

    early = datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=90)
    start_dt = f"{early.strftime('%Y-%m-%d')} 09:30:00"
    end_date = f"{start_date} 15:00:00"

    client = DHANClient(access_token=settings.DATA_DHAN_ACCESS_TOKEN)
    df = client.get_intraday_ohlc(
        security_id=security_id,
        start_date=start_dt,
        end_date=end_date,
        interval=interval
    )
    plotter = EMACandlestickPlotter(df, symbol)
    fig = plotter.build_figure()
    chart_json = fig.to_json()

    return render(request, "market/stock_chart.html", {
        "chart_json": chart_json,
        "symbol": symbol,
    })


# Aws server set time to IST
# sudo timedatectl set-timezone Asia/Kolkata
# $ timedatectl
#                       Local time: Sun 2025-06-22 14:07:00 IST
#                   Universal time: Sun 2025-06-22 08:37:00 UTC
#                         RTC time: Sun 2025-06-22 08:37:00
#                        Time zone: Asia/Kolkata (IST, +0530)
#        System clock synchronized: yes
#  systemd-timesyncd.service active: yes
#                  RTC in local TZ: no
# CRON Command
# */15 9-15 * * 1-5 /path/to/venv/bin/python /path/to/project/manage.py check_ema_crossover >> /path/to/logs/ema_crossover.log 2>&1
