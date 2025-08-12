import csv
import io
import re
from datetime import timedelta, date, datetime
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


SYMBOL_TOKEN_RE = re.compile(r"^[A-Z0-9]+")
WEEKEND = {5, 6}  # Sat=5, Sun=6


def _debug(msg, **kw):
    print("DEBUG:", json.dumps({"msg": msg, **kw}, default=str, indent=2))


def weekday_only_back(anchor: date, n: int) -> date:
    d = anchor
    count = 0
    while count < n:
        d -= timedelta(days=1)
        if d.weekday() not in WEEKEND:
            count += 1
    return d


def list_exchange_sessions_back(anchor: date, n: int, holidays: set) -> list:
    """List the last `n` exchange sessions prior to `anchor` (skip weekends + holidays)."""
    sessions = []
    d = anchor
    while len(sessions) < n:
        d -= timedelta(days=1)
        if d.weekday() not in WEEKEND and d not in holidays:
            sessions.append(d)
    return sessions  # newest -> older


@login_required
def upload_trendlines_csv(request):
    if request.method == "POST" and request.FILES.get("sheet1") and request.FILES.get("sheet2"):
        file1 = request.FILES["sheet1"]
        file2 = request.FILES["sheet2"]

        def read_file(uploaded):
            name = (uploaded.name or "").lower()
            raw = uploaded.read()
            if name.endswith(".csv"):
                return pd.read_csv(io.StringIO(raw.decode("utf-8")))
            return pd.read_excel(io.BytesIO(raw))

        try:
            df1 = read_file(file1)
            df2 = read_file(file2)

            # Required columns
            c_txtname = next((c for c in df1.columns if c.strip().lower() in {"txtname", "name", "symbol"}), None)
            c_days = next((c for c in df1.columns if c.strip().lower() in {"days", "offset", "daysoffset"}), None)
            if not c_txtname or not c_days:
                messages.error(request, "Sheet1 must contain symbol (txtName/name/symbol) and days (days/offset).")
                return redirect("market:upload_trendlines_csv")

            need_cols_df2 = {"scrip", "scale", "startDay"}
            if not need_cols_df2.issubset({c.strip() for c in df2.columns}):
                messages.error(request, "Sheet2 must contain 'scrip', 'scale', and 'startDay'.")
                return redirect("market:upload_trendlines_csv")

            # DHAN symbol map
            try:
                client = DHANClient(access_token=settings.DATA_DHAN_ACCESS_TOKEN)
                symbol_result = client.get_symbols()
            except Exception as e:
                messages.error(request, f"DHAN symbols error: {e}")
                return redirect("market:upload_trendlines_csv")

            if not isinstance(symbol_result, dict) or "instrument_list" not in symbol_result:
                messages.error(request, "Failed to fetch symbol data from DHAN.")
                return redirect("market:upload_trendlines_csv")

            symbol_lookup = {
                (item.get("symbol") or "").strip().upper(): (item.get("security_id") or "").strip()
                for item in symbol_result["instrument_list"]
                if item.get("symbol") and item.get("security_id")
            }

            # Existing (symbol, angle)
            try:
                existing_keys = set(
                    (obj.symbol.strip().upper(), float(obj.angles[0]))
                    for obj in TrendLine.objects.all()
                    if getattr(obj, "angles", None)
                )
            except Exception:
                existing_keys = set(
                    (obj.symbol.strip().upper(), float(getattr(obj, "angle", 0.0)))
                    for obj in TrendLine.objects.all()
                )

            # Meta lookup
            df2["_SCRIP_NORM_"] = df2["scrip"].astype(str).str.strip().str.upper()
            meta_map = df2.set_index("_SCRIP_NORM_")[["scale", "startDay"]]

            ANGLES = [45.0]
            now_naive = timezone.now().replace(tzinfo=None)

            new_entries = []
            duplicates = 0
            prepared = 0

            for _, row in df1.iterrows():
                raw_symbol = str(row[c_txtname]).strip() if pd.notna(row[c_txtname]) else ""
                if not raw_symbol:
                    continue

                token = SYMBOL_TOKEN_RE.findall(raw_symbol.upper())
                symbol = token[0] if token else raw_symbol.split()[0].upper()

                if symbol not in meta_map.index:
                    continue

                try:
                    meta = meta_map.loc[symbol]
                    scale = float(meta["scale"])
                except Exception:
                    continue

                try:
                    days_offset = int(row[c_days])
                    if days_offset < 0:
                        continue
                except Exception:
                    continue

                security_id = symbol_lookup.get(symbol)
                if not security_id:
                    continue

                # History fetch + normalize
                try:
                    hist_df = client.get_full_history(security_id)
                except Exception:
                    continue

                if hist_df is None or len(hist_df) == 0:
                    continue

                hist_df = hist_df.copy()
                hist_df.columns = [str(c).strip().lower() for c in hist_df.columns]

                if "timestamp" in hist_df.columns:
                    hist_df = hist_df.reset_index(drop=True)
                else:
                    idx_name = (hist_df.index.name or "").strip()
                    hist_df = hist_df.reset_index()
                    src_name = (idx_name if idx_name else "index")
                    src_name_lc = str(src_name).strip().lower()
                    if src_name_lc not in hist_df.columns:
                        candidate = next((c for c in ["index", idx_name, "timestamp", "date", "datetime"] if c and c in hist_df.columns), None)
                        if candidate is None:
                            continue
                        src_name_lc = candidate
                    hist_df = hist_df.rename(columns={src_name_lc: "timestamp"})

                if "low" not in hist_df.columns:
                    for alt in ("l", "lo", "min", "lowprice"):
                        if alt in hist_df.columns:
                            hist_df["low"] = hist_df[alt]
                            break
                if "low" not in hist_df.columns:
                    continue

                hist_df["timestamp"] = pd.to_datetime(hist_df["timestamp"], errors="coerce")
                hist_df = hist_df.dropna(subset=["timestamp"])
                hist_df = hist_df[hist_df["timestamp"] <= pd.Timestamp(now_naive)]
                if hist_df.empty:
                    continue

                # Sort latest→oldest and dedupe to one row per date
                hist_df = hist_df.sort_values("timestamp", ascending=False).reset_index(drop=True)
                hist_df["date_only"] = hist_df["timestamp"].dt.date
                hist_df = hist_df.drop_duplicates(subset=["date_only"], keep="first").reset_index(drop=True)

                # --- Symbol-days pick (fixed off-by-one) ---
                idx_pick = max(int(days_offset) - 1, 0)
                if idx_pick > len(hist_df) - 1:
                    continue

                target_row = hist_df.iloc[idx_pick]
                start_date = target_row["date_only"]
                start_price = float(target_row["low"])

                for angle in ANGLES:
                    key = (symbol, float(angle))
                    is_dup = key in existing_keys
                    if is_dup:
                        duplicates += 1

                    new_entries.append({
                        "symbol": symbol,
                        "start_date": str(start_date),
                        "angle": float(angle),
                        "price_to_bar_ratio": float(scale),
                        "start_price": start_price,
                        "security_id": security_id,
                        "is_duplicate": is_dup,
                        "index_used": int(idx_pick),
                    })
                    prepared += 1

            if not new_entries:
                messages.warning(request, "No entries prepared.")
                return redirect("market:upload_trendlines_csv")

            request.session["review_entries"] = json.loads(json.dumps(new_entries, default=str))
            messages.success(request, f"Prepared {prepared} entries (duplicates: {duplicates}).")
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

