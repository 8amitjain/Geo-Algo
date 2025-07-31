import environ
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env()
environ.Env.read_env(os.path.join(BASE_DIR, "geo_algo/local_env.env"))

SECRET_KEY = 'django-insecure-j2e(v&w4(rjfgcp-*&@4-j@)$efxhhg2(tfp951amhb=4^r#+%'
# DEBUG = True
DEBUG = False
print(DEBUG)
ALLOWED_HOSTS = ['*']


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.postgres',

    'market',
    'dhan',
    'home',
    'users',
    'variables',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'geo_algo.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'geo_algo.wsgi.application'


# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3',
#     }
# }
host = '127.0.0.1' if DEBUG else '13.126.174.197'
# host = '13.126.174.197' if DEBUG else '13.126.174.197'
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'geo_algo',
        'USER': 'postgres',
        'PASSWORD': 'postgres',
        'HOST': host,
        'PORT': '5432',
    }
}


AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / "static/"

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AMIT_TRADING_DHAN_ACCESS_TOKEN = env("AMIT_TRADING_DHAN_ACCESS_TOKEN")
AMIT_CLIENT_ID = env("AMIT_CLIENT_ID")
ANAND_TRADING_DHAN_ACCESS_TOKEN = env("ANAND_TRADING_DHAN_ACCESS_TOKEN")
ANAND_CLIENT_ID = env("ANAND_CLIENT_ID")
DATA_DHAN_ACCESS_TOKEN = env("DATA_DHAN_ACCESS_TOKEN")
DATA_CLIENT_ID = env("DATA_CLIENT_ID")


DEFAULT_FROM_EMAIL = "amit.intelus@gmail.com"
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = "amit.intelus@gmail.com"
EMAIL_HOST_PASSWORD = "loxjtkgrjhgoarus"

if DEBUG:
    EMAIL_RECIPIENTS = ["8amitjain@gmail.com"]
else:
    EMAIL_RECIPIENTS = ["8amitjain@gmail.com", "anandkene3073@gmail.com"]

# User
LOGIN_URL = '/users/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'
AUTH_USER_MODEL = 'users.User'

DATA_UPLOAD_MAX_MEMORY_SIZE = 52428800   # 50MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 52428800   # 50MB
