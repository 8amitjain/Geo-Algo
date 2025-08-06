import csv
import io
import subprocess
from datetime import datetime, timedelta
import decimal
from decimal import Decimal
import json
import matplotlib
import pandas as pd
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.http import HttpResponse

import threading
from django.core.management import call_command

from geo_algo import settings

from .dhan import DHANClient
from .models import TrendLine, TrendLineCheck
from .plotters import EMACandlestickPlotter, InteractiveChartPlotter
from .services import TrendLinePersistenceService
from .utils import buy_sell_stock

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
    ratio = float(request.GET.get('price_to_bar_ratio', 1))
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
    # start_date = request.GET.get("start_date", "2025-06-02")
    interval = int(request.GET.get("interval", "15"))
    start_date = datetime.now()
    early = datetime.strptime(str(start_date)[:10], "%Y-%m-%d") - timedelta(days=90)
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

# TODO filter based on angle and script
# Test delete
# Need option delete all
# Need to show old and new - option to choose from either.


@login_required
def upload_trendlines_csv(request):
    if request.method == "POST" and request.FILES.get("sheet1") and request.FILES.get("sheet2"):
        file1 = request.FILES["sheet1"]
        file2 = request.FILES["sheet2"]

        def read_file(file):
            if file.name.lower().endswith(".csv"):
                return pd.read_csv(io.StringIO(file.read().decode("utf-8")))
            else:
                return pd.read_excel(file)

        try:
            df1 = read_file(file1)
            df2 = read_file(file2)

            client = DHANClient(access_token=settings.DATA_DHAN_ACCESS_TOKEN)
            symbol_result = client.get_symbols()

            if not isinstance(symbol_result, dict) or "instrument_list" not in symbol_result:
                messages.error(request, "Failed to fetch symbol data from DHAN.")
                return redirect("market:upload_trendlines_csv")

            instrument_list = symbol_result["instrument_list"]
            symbol_lookup = {
                item["symbol"].strip().upper(): item["security_id"].strip()
                for item in instrument_list
            }

            # Create set of existing (symbol, angle) pairs
            existing_keys = set(
                (obj.symbol, obj.angles[0]) for obj in TrendLine.objects.all()
            )

            new_entries = []
            for _, row in df1.iterrows():
                raw_symbol = str(row["txtName"]).strip()
                symbol = raw_symbol.split()[0].upper()

                meta = df2[df2["scrip"].str.upper() == symbol]
                if meta.empty:
                    continue

                try:
                    scale = float(meta.iloc[0]["scale"])
                    start_day = int(meta.iloc[0]["startDay"])
                    days_offset = int(row["days"])
                except Exception:
                    continue

                security_id = symbol_lookup.get(symbol)
                if not security_id:
                    continue

                hist_df = client.get_full_history(security_id)
                if hist_df.empty or len(hist_df) < days_offset:
                    continue

                hist_df = hist_df.sort_index()[::-1].reset_index()
                if days_offset >= len(hist_df):
                    continue

                target_row = hist_df.iloc[days_offset]
                start_date = target_row["timestamp"].date()
                start_price = target_row["low"]

                for angle in [45, 63.75, 26.25]:
                    new_entry = {
                        "symbol": symbol,
                        "start_date": str(start_date),
                        "angle": float(angle),
                        "price_to_bar_ratio": float(scale),
                        "start_price": float(start_price),
                        "security_id": security_id
                    }
                    key = (symbol, angle)
                    if key in existing_keys:
                        new_entry["is_duplicate"] = True
                    else:
                        new_entry["is_duplicate"] = False
                    new_entries.append(new_entry)

            request.session["review_entries"] = json.loads(json.dumps(new_entries, default=str))
            return redirect("market:resolve_trendline_duplicates")

        except Exception as e:
            messages.error(request, f"Error processing files: {e}")
            return redirect("market:upload_trendlines_csv")

    return render(request, "market/upload_trendlines_csv.html")


@login_required
def resolve_trendline_duplicates(request):
    if request.method == "POST":
        total = int(request.POST.get("total", 0))
        skip_all = request.POST.get("skip_all")

        entries = request.session.get("review_entries", [])
        created = 0

        for i in range(total):
            if skip_all or request.POST.get(f"skip_{i}"):
                continue

            try:
                symbol = request.POST.get(f"symbol_{i}")
                angle = float(request.POST.get(f"angle_{i}"))
                start_date = request.POST.get(f"start_date_{i}")
                scale = float(request.POST.get(f"scale_{i}"))
                start_price = float(request.POST.get(f"start_price_{i}"))
                security_id = request.POST.get(f"security_id_{i}")

                TrendLine.objects.create(
                    symbol=symbol,
                    security_id=security_id,
                    start_date=start_date,
                    angles=[angle],
                    price_to_bar_ratio=scale,
                    start_price=start_price
                )
                created += 1
            except Exception as e:
                print("Error creating:", e)

        # Clear session and start background update
        request.session.pop("review_entries", None)
        threading.Thread(target=lambda: call_command("update_trendline_percent_diff")).start()

        messages.success(request, f"{created} trend lines created.")
        return redirect("market:trendline_list")

    entries = request.session.get("review_entries", [])
    return render(request, "market/review_trendline_duplicates.html", {"entries": entries})


def json_safe(data):
    # Convert Decimal to float, datetime to string, etc.
    safe = []
    for item in data:
        safe.append({
            k: float(v) if isinstance(v, decimal.Decimal) else str(v) if hasattr(v, "isoformat") else v
            for k, v in item.items()
        })
    return safe


@login_required
def trendline_delete(request, pk):
    tl = get_object_or_404(TrendLine, pk=pk)

    if request.method == "POST":
        tl.delete()
        messages.success(request, f"Trend line for {tl.symbol} deleted.")
        return redirect("market:trendline_list")

    # If GET, redirect back with warning (optional, you can show a confirm page too)
    messages.error(request, "Deletion must be confirmed via POST.")
    return redirect("market:trendline_list")


@login_required
def trendline_list(request):
    qs = TrendLine.objects.all()

    # --- gather GET filters ---
    symbol = request.GET.get("symbol", "").strip()
    start_date = request.GET.get("start_date", "").strip()
    created = request.GET.get("created_at", "").strip()
    touched = request.GET.get("touched", "")
    purchased = request.GET.get("purchased", "")
    angle = request.GET.get("angle", "")

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

    if angle:
        qs = qs.filter(angles__icontains=angle)

    sort_by = request.GET.get("sort", "distance")
    reverse = request.GET.get("direction") == "desc"

    trendlines = list(qs)  # Force evaluation for sorting in Python

    if sort_by == "distance":
        trendlines.sort(
            key=lambda tl: tl.percent_difference_cached if tl.percent_difference_cached is not None else float('-inf'),
            reverse=reverse
        )

    # pass current filter values back to template
    context = {
        "trendlines": trendlines,
        "trendlines_count": qs.count(),
        "filters": {
            "symbol": symbol,
            "start_date": start_date,
            "created_at": created,
            "touched": touched,
            "purchased": purchased,
            "angle": angle,
        },
        "current_sort": sort_by,
        "current_direction": "desc" if reverse else "asc",
    }
    return render(request, "market/trendline_list.html", context)


@login_required
def buy_stock_view(request):
    if request.method == "POST":
        try:
            risk = float(request.POST["risk_per_unit"])
            price = float(request.POST["cross_price"])
            sec_id = request.POST["security_id"]
            symbol = request.POST["symbol"]

            # print(risk, price, sec_id, symbol)
            buy_sell_stock(risk_per_unit=risk, cross_price=price, security_id=sec_id, symbol=symbol, transaction_type="BUY")
            messages.success(request, f"Buy order placed for {symbol}")
        except Exception as e:
            messages.error(request, f"Error placing buy order: {e}")
    return redirect(request.META.get("HTTP_REFERER", "/"))


@login_required
def sell_stock_view(request):
    if request.method == "POST":
        try:
            risk = float(request.POST["risk_per_unit"])
            price = float(request.POST["sell_price"])
            sec_id = request.POST["security_id"]
            symbol = request.POST["symbol"]

            buy_sell_stock(risk_per_unit=risk, cross_price=price, security_id=sec_id, symbol=symbol, transaction_type="SELL")
            messages.success(request, f"Sell order placed for {symbol}")
        except Exception as e:
            messages.error(request, f"Error placing sell order: {e}")
    return redirect(request.META.get("HTTP_REFERER", "/"))


# Create both model list view and details view
# Create user login - basic - Admin creates user - any user can login


# CRON Command
# */15 9-15 * * MON-FRI /home/ubuntu/Geo-Algo/venv/bin/python /home/ubuntu/Geo-Algo/manage.py check_ema_crossover >> /home/ubuntu/Geo-Algo/logs/ema_crossover.log 2>&1
# */15 9-15 * * MON-FRI /home/ubuntu/Geo-Algo/venv/bin/python /home/ubuntu/Geo-Algo/manage.py check_trend_lines >> /home/ubuntu/Geo-Algo/logs/check_trend_lines.log 2>&1
# */15 9-15 * * MON-FRI /home/ubuntu/Geo-Algo/venv/bin/python /home/ubuntu/Geo-Algo/manage.py check_break_high >> /home/ubuntu/Geo-Algo/logs/check_break_high.log 2>&1
# */15 9-15 * * MON-FRI /home/ubuntu/Geo-Algo/venv/bin/python /home/ubuntu/Geo-Algo/manage.py check_stop_loss >> /home/ubuntu/Geo-Algo/logs/check_stop_loss.log 2>&1
# 0 16 * * MON-FRI /home/ubuntu/Geo-Algo/venv/bin/python /home/ubuntu/Geo-Algo/manage.py  update_trendline_percent_diff >> /home/ubuntu/Geo-Algo/logs/update_trendline_percent_diff.log 2>&1
# 0 8 * * * /home/ubuntu/Geo-Algo/venv/bin/python /home/ubuntu/Geo-Algo/manage.py  check_dhan_tokens >> /home/ubuntu/Geo-Algo/logs/dhan_token_check.log 2>&1
#
# # Deploy and test cron jobs logic and function
# http://13.126.174.197/market/
# http://13.126.174.197/market/chart.png?symbol=SBI+Life+Insurance&security_id=21808&start_price=low&start_date=2025-03-12&price_to_bar_ratio=4&angles=45,63.251&start_bar=1846
# http://13.126.174.197/admin/market/trendlinecheck/

