"""
Django settings for the dashboard analyst project.

Hosts two applications:
- `dashboard`: the original mock realisasi dashboard (no database).
- `finance`: the Financial Analyst Dashboard (SQLite for development,
  PostgreSQL for production see DATABASES).
"""

import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

from .database_config import database_config

BASE_DIR = Path(__file__).resolve().parent.parent

# Load only the explicitly selected local file. Vercel supplies process envs.
# Existing process variables take precedence; no automatic .env discovery.
if os.environ.get('DJANGO_ENV_FILE'):
    env_path = Path(os.environ['DJANGO_ENV_FILE'])
    if not env_path.is_file():
        raise ImproperlyConfigured('DJANGO_ENV_FILE does not point to a file.')
    load_dotenv(env_path, override=False, interpolate=False)

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-g(r9e+!%wd$#q+2wn)@nzaq0e4bf#=mk=0r9kub9%m5x6u$&wc')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DJANGO_DEBUG', 'false' if os.environ.get('VERCEL') else 'true').lower() in ('1', 'true', 'yes')
if os.environ.get('VERCEL') and not os.environ.get('DJANGO_SECRET_KEY'):
    raise ImproperlyConfigured('DJANGO_SECRET_KEY must be configured on Vercel.')

# Vercel sends the deployment host (e.g. dashboard-orpin-iota-64.vercel.app)
# as HTTP_HOST; allow any host here the app serves public mock data only.
ALLOWED_HOSTS = ['*']

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'dashboard',
    'finance',
    'django.contrib.staticfiles',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.common.CommonMiddleware',
    # Every manual revenue write is a POST and MUST carry a CSRF token (§34).
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    # PRIVATE BY DEFAULT: every view of this application requires a signed-in
    # user unless it opts out with @login_not_required. This is the single
    # enforcement point (see finance/middleware.py); must sit directly after
    # AuthenticationMiddleware so request.user is already resolved, and before
    # the response middleware below.
    'finance.middleware.AjaxLoginRequiredMiddleware',
    'dashboard.middleware.PrivateCacheMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
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
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'dashboard.wsgi.application'

DATABASES = {'default': database_config(os.environ, BASE_DIR)}

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/ref/settings/#static-files

# Operator sign-in. The whole application is private (see finance/middleware),
# so these settings decide where an unauthenticated visitor is sent and where a
# fresh sign-in lands: the Financial Overview at "/" (§2, §9). A valid ?next=
# still wins over LOGIN_REDIRECT_URL, which is how a deep link survives login.
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'

STATIC_URL = 'static/'
STATICFILES_DIRS = [
    BASE_DIR / 'public',
]
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Internationalization

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Caching (dashboard cache keys, see finance/services).
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}
