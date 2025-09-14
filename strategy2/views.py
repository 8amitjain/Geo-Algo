from django.shortcuts import render, get_object_or_404, redirect
from .models import StrategyStock
import plotly.graph_objects as go
from django.utils import timezone
from market.dhan import DHANClient
from django.conf import settings
import pandas as pd
from django.contrib import messages


def stock_list(request):
    qs = StrategyStock.objects.filter(active=True)

    # filters
    symbol = request.GET.get("symbol", "").strip()
    reversal = request.GET.get("reversal", "")
    purchased = request.GET.get("purchased", "")

    if symbol:
        qs = qs.filter(name__icontains=symbol)
    if reversal == "yes":
        qs = qs.filter(reversal_bar_found=True)
    elif reversal == "no":
        qs = qs.filter(reversal_bar_found=False)
    if purchased == "yes":
        qs = qs.filter(is_purchased=True)
    elif purchased == "no":
        qs = qs.filter(is_purchased=False)

    context = {
        "stocks": qs,
        "filters": {
            "symbol": symbol,
            "reversal": reversal,
            "purchased": purchased,
        }
    }

    client = DHANClient(settings.DATA_DHAN_ACCESS_TOKEN)
    resp = client.get_symbols()
    if resp['status_code'] != 200:
        return render(request, 'market/error.html', resp)
    context['instrument_list'] = resp['instrument_list']
    return render(request, "strategy2/stock_list.html", context)


def add_stock(request):
    if request.method == "POST":
        name = request.POST.get("name")
        security_id = request.POST.get("security_id")

        if name and security_id:
            StrategyStock.objects.get_or_create(
                name=name.strip(),
                security_id=security_id.strip(),
                defaults={"active": True}
            )
        return redirect("strategy2:stock_list")

    return redirect("strategy2:stock_list")


def delete_stock(request, stock_id):
    stock = get_object_or_404(StrategyStock, id=stock_id)
    if request.method == "POST":
        stock.delete()
        messages.success(request, f"Stock {stock.name} deleted successfully.")
    return redirect("strategy2:stock_list")  # replace with your list view name


def stock_chart(request, stock_id):
    stock = get_object_or_404(StrategyStock, pk=stock_id)
    client = DHANClient(access_token=settings.DATA_DHAN_ACCESS_TOKEN)

    # Get last 60 days of daily candles
    df = client.get_ticker_data(
        stock.security_id,
        (timezone.now() - timezone.timedelta(days=60)).strftime("%Y-%m-%d")
    )

    if df.empty:
        return render(request, "strategy2/stock_chart.html", {"stock": stock, "plot_div": None})

    # --- Plotly candlestick chart ---
    fig = go.Figure(data=[
        go.Candlestick(
            x=df.index,
            open=df['open'],
            high=df['high'],
            low=df['low'],
            close=df['close'],
            name="Candles"
        )
    ])

    # === Reversal Bar 1 ===
    if stock.reversal_bar1_date and stock.reversal_bar1_high:
        r1_date = pd.to_datetime(stock.reversal_bar1_date)
        if r1_date in df.index:
            fig.add_trace(go.Scatter(
                x=[r1_date],
                y=[stock.reversal_bar1_high],
                mode="markers+text",
                marker=dict(color="blue", size=12, symbol="triangle-up"),
                text=["R1"],
                textposition="top center",
                name="Reversal 1"
            ))

    # === Reversal Bar 2 ===
    if stock.reversal_bar2_date and stock.reversal_bar2_high:
        r2_date = pd.to_datetime(stock.reversal_bar2_date)
        if r2_date in df.index:
            fig.add_trace(go.Scatter(
                x=[r2_date],
                y=[stock.reversal_bar2_high],
                mode="markers+text",
                marker=dict(color="purple", size=12, symbol="triangle-up"),
                text=["R2"],
                textposition="top center",
                name="Reversal 2"
            ))

    # === Entry Price ===
    if stock.entry_price:
        fig.add_hline(
            y=stock.entry_price,
            line=dict(color="green", dash="dash"),
            annotation_text=f"Entry ({stock.entry_price:.2f})",
            annotation_position="top left"
        )

    # === TSL ===
    if stock.stop_loss:
        fig.add_hline(
            y=stock.stop_loss,
            line=dict(color="red", dash="dot"),
            annotation_text=f"TSL ({stock.stop_loss:.2f})",
            annotation_position="bottom left"
        )

    # Layout
    fig.update_layout(
        title=f"{stock.name} ({stock.security_id})",
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        height=600,
    )

    plot_div = fig.to_html(full_html=False)
    return render(request, "strategy2/stock_chart.html", {"stock": stock, "plot_div": plot_div})
