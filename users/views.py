from django.shortcuts import render, redirect
from django.contrib import messages
from .forms import UserRegisterForm
from django.template import RequestContext
from django.contrib.auth import authenticate, login
from .models import User, UserLog
from django.contrib.auth import logout


def log_user_action(user, action, ip_address):
    UserLog.objects.create(user=user, action=action, ip_address=ip_address)


def logout_view(request):
    logout(request)
    return redirect('/')


def login_view(request):
    if request.method == 'POST':
        email = request.POST['email']
        password = request.POST['password']
        user_obj = User.objects.filter(email=email).first()
        if user_obj is not None:
            if user_obj.is_active is True:

                user = authenticate(request, email=email, password=password)
                if user is not None:
                    login(request, user)
                    log_user_action(request.user, 'Logged in', request.META.get('REMOTE_ADDR'))
                    return redirect('/')
                else:
                    messages.error(request, f'Invalid email or password')
                    return render(request, 'users/login.html')

            messages.error(request, f'Account not active. Ask admin to activate your account')
            return render(request, 'users/login.html')
        else:
            messages.error(request, f'Account does not exist with this email')
            return render(request, 'users/login.html')
    else:
        return render(request, 'users/login.html')


def register(request):
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            form.save()
            # username = form.cleaned_data.get('username')
            messages.success(request, f'Account created')
            return redirect('register')
    else:
        form = UserRegisterForm()
    return render(request, 'users/register.html', {'form': form})


def handler404(request, *args, **argv):
    response = render(request, 'users/404.html')
    response.status_code = 404
    return response


def handler500(request, *args, **argv):
    response = render(request, 'users/404.html')
    response.status_code = 500
    return response
