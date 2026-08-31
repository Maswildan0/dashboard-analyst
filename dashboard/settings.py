"""
Django settings for the dashboard analyst project.

Migrated from the original Laravel 13 application; the routes, filter
logic, and mock dataset are preserved 1:1 (see dashboard/views.py).
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-g(r9e+!%wd$#q+2wn)@nzaq0e4bf#=mk=0r9kub9%m5x6u$&wc'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['127.0.0.1', 'localhost']

# Application definition

INSTALLED_APPS = [
    'dashboard',
    'django.contrib.staticfiles',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'dashboard.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
            ],
        },
    },
]

WSGI_APPLICATION = 'dashboard.wsgi.application'

# No database: the dashboard is powered entirely by the deterministic mock
# dataset in dashboard/views.py (same as the original Laravel controller).
DATABASES = {}

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/ref/settings/#static-files

STATIC_URL = 'static/'
STATICFILES_DIRS = [
    BASE_DIR / 'public',
]

# Internationalization

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
