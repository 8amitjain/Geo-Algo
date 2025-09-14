from django.urls import path
from . import views

app_name = 'strategy2'

urlpatterns = [
    path("stocks/", views.stock_list, name="stock_list"),
    path("stocks/add/", views.add_stock, name="add_stock"),
    path("stocks/<int:stock_id>/delete/", views.delete_stock, name="delete_stock"),
    path("stocks/<int:stock_id>/chart/", views.stock_chart, name="stock_chart"),
]
