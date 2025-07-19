from django.urls import path
from . import views

app_name = 'market'

urlpatterns = [
    path("", views.stock_form, name="stock_form"),
    path("chart.png", views.stock_chart, name="stock_chart"),

    path("trendlines/upload/", views.upload_trendlines_csv, name="upload_trendlines_csv"),
    path("trendlines/", views.trendline_list, name="trendline_list"),
    path("trendline/<int:pk>/delete/", views.trendline_delete, name="trendline_delete"),

    path("ema_crossover_chart", views.candlestick_chart, name="stock_chart_ema"),

    path("buy/", views.buy_stock_view, name="buy_stock"),
    path("sell/", views.sell_stock_view, name="sell_stock"),

]
