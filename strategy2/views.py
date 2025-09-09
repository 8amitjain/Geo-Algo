from django.shortcuts import render, get_object_or_404
from .models import StrategyStock
import plotly.graph_objects as go
from django.utils import timezone
from market.dhan import DHANClient
from django.conf import settings
import pandas as pd


def stock_list(request):
    stocks = StrategyStock.objects.filter(active=True)
    return render(request, "strategy2/stock_list.html", {"stocks": stocks})


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

    # === Reversal Bar(s) ===
    if stock.reversal_bar_high and stock.reversal_bar_date:
        r1_date = pd.to_datetime(stock.reversal_bar_date)
        if r1_date in df.index:
            r1_price = df.loc[r1_date, "high"]

            # Add marker
            fig.add_trace(go.Scatter(
                x=[r1_date],
                y=[r1_price],
                mode="markers+text",
                marker=dict(color="blue", size=12, symbol="triangle-up"),
                text=["R1"],
                textposition="top center",
                name="Reversal 1"
            ))

    # Optional: If you track second reversal bar (store separately in model)
    if hasattr(stock, "reversal_bar2_date") and stock.reversal_bar2_date:
        r2_date = pd.to_datetime(stock.reversal_bar2_date)
        if r2_date in df.index:
            r2_price = df.loc[r2_date, "high"]
            fig.add_trace(go.Scatter(
                x=[r2_date],
                y=[r2_price],
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
