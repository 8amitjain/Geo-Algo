from django.urls import path
from . import views

app_name = 'strategy2'

urlpatterns = [
    path("stocks/", views.stock_list, name="stock_list"),
    path("stocks/<int:stock_id>/chart/", views.stock_chart, name="stock_chart"),
]
