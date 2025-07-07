from geo_algo import settings
from .plotters import InteractiveChartPlotter, EMACandlestickPlotter
from .services import TrendLinePersistenceService
from .dhan import DHANClient
from django.contrib.auth.decorators import login_required

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
from .models import *

matplotlib.use("Agg")


"""
Flow in action
User visits /market/ → sees the form.

Submits with e.g. ?symbol=TCS&start_price=3450&start_bar_index=30&price_to_bar_ratio=1&angles=45,65

Django calls stock_chart, generates a PNG on-the-fly, and the <img> tag displays it in the same page.

This keeps your DHAN logic DRY (you’re re-using the same client/plotter classes), and all secrets stay in .env.
"""
# http://127.0.0.1:8000/market/chart.png?symbol=SBI+Life+Insurance&security_id=21808&start_price=low&start_date=2025-03-12&price_to_bar_ratio=4&angles=45,63.251&start_bar=1846

@login_required
def stock_form(request):
    client = DHANClient(settings.DATA_DHAN_ACCESS_TOKEN)
    resp = client.get_symbols()
    if resp['status_code'] != 200:
        return render(request, 'market/error.html', resp)
    return render(request, 'market/stock_form.html', {'instrument_list': resp['instrument_list']})


@login_required
def stock_chart(request):
    symbol = request.GET.get('symbol', 'TCS')
    start_price = request.GET.get('start_price', 'low')
    security_id = request.GET.get('security_id')
    start_date = request.GET.get('start_date')
    ratio = int(request.GET.get('price_to_bar_ratio', 1))
    angles = [float(a) for a in request.GET.get('angles', '45,65').split(',')]

    client = DHANClient(settings.DATA_DHAN_ACCESS_TOKEN)
    df = client.get_full_history(security_id)

    plotter = InteractiveChartPlotter(df, symbol, angles, ratio, start_price, start_date)
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

    return render(request, "market/stock_chart.html", {
            "chart_json": chart_json,
            "symbol": symbol,
        })


# http://127.0.0.1:8000/market/ema_crossover_chart?security_id=21808&interval=15&date=2025-05-30
@login_required
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


@login_required
def trendline_list(request):
    qs = TrendLine.objects.all()

    # --- gather GET filters ---
    symbol = request.GET.get("symbol", "").strip()
    start_date = request.GET.get("start_date", "").strip()
    created = request.GET.get("created_at", "").strip()
    touched = request.GET.get("touched", "")
    purchased = request.GET.get("purchased", "")

    # --- apply filters ---
    if symbol:
        qs = qs.filter(symbol__icontains=symbol)

    if start_date:
        try:
            dt = datetime.strptime(start_date, "%Y-%m-%d").date()
            qs = qs.filter(start_date=dt)
        except ValueError:
            pass

    if created:
        try:
            cd = datetime.strptime(created, "%Y-%m-%d").date()
            qs = qs.filter(created_at__date=cd)
        except ValueError:
            pass

    if touched in ["yes", "no"]:
        want = touched == "yes"
        qs = qs.filter(
            checks__touched=want
        ).distinct()

    if purchased in ["yes", "no"]:
        want = purchased == "yes"
        # assuming you have a Purchase model with FK `purchase__trend_line`
        qs = qs.filter(
            checks__purchased=want
        ).distinct()

    # pass current filter values back to template
    context = {
        "trendlines": qs.order_by("-created_at"),
        "filters": {
            "symbol": symbol,
            "start_date": start_date,
            "created_at": created,
            "touched": touched,
            "purchased": purchased,
        }
    }
    return render(request, "market/trendline_list.html", context)


# Create both model list view and details view
# Create user login - basic - Admin creates user - any user can login


# CRON Command
# */15 9-15 * * MON-FRI /home/ubuntu/Geo-Algo/venv/bin/python /home/ubuntu/Geo-Algo/manage.py check_ema_crossover >> /home/ubuntu/Geo-Algo/logs/ema_crossover.log 2>&1
# */15 9-15 * * MON-FRI /home/ubuntu/Geo-Algo/venv/bin/python /home/ubuntu/Geo-Algo/manage.py check_trend_lines >> /home/ubuntu/Geo-Algo/logs/check_trend_lines.log 2>&1


# Deploy and test cron jobs logic and function
# http://13.126.174.197/market/
# http://13.126.174.197/market/chart.png?symbol=SBI+Life+Insurance&security_id=21808&start_price=low&start_date=2025-03-12&price_to_bar_ratio=4&angles=45,63.251&start_bar=1846
# http://13.126.174.197/admin/market/trendlinecheck/

