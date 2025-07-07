from django.urls import path
from . import views

app_name = 'variables'

urlpatterns = [
    path("vibration-point/", views.vibration_point_detail, name="vibration_point_detail"),

]
