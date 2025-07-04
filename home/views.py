from django.shortcuts import render
from django.shortcuts import redirect
from django.urls import reverse


def home_redirect(request):
    if request.user.is_authenticated:
        # Redirect to the charts_data page
        return redirect(reverse('market:stock_form'))
    else:
        # Redirect to the login page
        # return redirect(reverse('advertising_report:summary'))
        return redirect(reverse('login'))
