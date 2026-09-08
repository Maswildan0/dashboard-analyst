"""
Django settings for the dashboard analyst project.

Hosts two applications:
- `dashboard`: the original mock realisasi dashboard (no database).
- `finance`: the Financial Analyst Dashboard (SQLite for development,
  PostgreSQL for production see DATABASES).
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

import dj_database_url  # noqa: E402 (parses DATABASE_URL -> Django settings)

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-g(r9e+!%wd$#q+2wn)@nzaq0e4bf#=mk=0r9kub9%m5x6u$&wc')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DJANGO_DEBUG', 'true').lower() in ('1', 'true', 'yes')

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
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
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

# Database selection.
#   1) DATABASE_URL set  -> use it (production: Neon PostgreSQL on Vercel;
#                           local override when exported). No credentials are
#                           hard-coded anywhere; read purely from env.
#   2) DB_ENGINE=postgres -> PostgreSQL via discrete PG* env vars.
#   3) otherwise          -> local MariaDB/MySQL (XAMPP financial_dashboard).
#   VERCEL (no DATABASE_URL) falls back to /tmp SQLite so cold start works.
_db_url = os.environ.get('DATABASE_URL')
if not _db_url:
    # Vercel Neon integrations export DATABASE_POSTGRES_URL (pooled) and
    # DATABASE_URL_UNPOOLED; fall back to them so the app uses Neon without
    # requiring a duplicate DATABASE_URL variable.
    for cand in ('DATABASE_POSTGRES_URL', 'DATABASE_URL_UNPOOLED', 'DATABASE_POSTGRES_URL_NON_POOLING'):
        v = os.environ.get(cand)
        if v and 'postgres' in v and '[SENSITIVE]' not in v:
            _db_url = v
            break
if _db_url:
    DATABASES = {
        'default': dj_database_url.parse(
            _db_url,
            conn_max_age=600,
            ssl_require='sslmode=require' in _db_url.lower() or 'neon.tech' in _db_url.lower(),
        )
    }
    # Serverless-friendly pooling is handled by Neon's pooled endpoint in the
    # connection string; keep Django conservative.
    if DATABASES['default']['ENGINE'].endswith('postgresql'):
        DATABASES['default'].setdefault('CONN_MAX_AGE', 60)
elif os.environ.get('DB_ENGINE') == 'postgres':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME', 'financial_dashboard'),
            'USER': os.environ.get('DB_USER', 'postgres'),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', '127.0.0.1'),
            'PORT': os.environ.get('DB_PORT', '5432'),
        }
    }
elif os.environ.get('VERCEL'):
    # Serverless cold start without DATABASE_URL: keep a scratch SQLite in /tmp
    # so build/migrate can run (real deployments always set DATABASE_URL).
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': Path('/tmp/db.sqlite3'),
        }
    }
else:
    # Local default: MariaDB/MySQL (XAMPP). Backend shim relaxes Django 6's
    # MariaDB >= 10.11 requirement and disables RETURNING below 10.5.
    DATABASES = {
        'default': {
            'ENGINE': 'dashboard.db_backends.mariadb',
            'NAME': os.environ.get('DB_NAME', 'financial_dashboard'),
            'USER': os.environ.get('DB_USER', 'root'),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', '127.0.0.1'),
            'PORT': os.environ.get('DB_PORT', '3306'),
            'OPTIONS': {'charset': 'utf8mb4'},
        }
    }

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/ref/settings/#static-files

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
