from django.urls import path
from . import views

urlpatterns = [
    path("", views.stock_form, name="stock_form"),
    path("chart.png", views.stock_chart, name="stock_chart"),
    path("ema_crossover_chart", views.candlestick_chart, name="stock_chart_ema"),
]
