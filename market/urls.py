from django.urls import path
from . import views

app_name = 'market'

urlpatterns = [
    path("", views.stock_form, name="stock_form"),
    path("chart.png", views.stock_chart, name="stock_chart"),

    path("ema_crossover_chart", views.candlestick_chart, name="stock_chart_ema"),

    path("trendlines/", views.trendline_list, name="trendline_list"),

]
