"""Environment-only database configuration. Never include credentials in errors."""
from urllib.parse import urlsplit

import dj_database_url
from django.core.exceptions import ImproperlyConfigured


def postgres_url_config(value):
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {'postgres', 'postgresql'}:
            raise ValueError
        if not parsed.hostname or not parsed.path.strip('/'):
            raise ValueError
        config = dj_database_url.parse(value, conn_max_age=0, conn_health_checks=True)
    except Exception:
        raise ImproperlyConfigured(
            'DATABASE_URL must be a valid PostgreSQL URL with a host and database.'
        ) from None
    options = config.setdefault('OPTIONS', {})
    if options.get('sslmode', 'require') not in {'require', 'verify-ca', 'verify-full'}:
        raise ImproperlyConfigured('PostgreSQL URL must require SSL.')
    options.setdefault('sslmode', 'require')
    options.setdefault('connect_timeout', 10)
    # Compatible with Neon's transaction pooler and QuerySet.iterator().
    config['DISABLE_SERVER_SIDE_CURSORS'] = True
    return config


def mysql_config(env, prefix='DB_'):
    return {
        'ENGINE': 'dashboard.db_backends.mariadb',
        'NAME': env.get(prefix + 'NAME', 'financial_dashboard'),
        'USER': env.get(prefix + 'USER', 'root'),
        'PASSWORD': env.get(prefix + 'PASSWORD', ''),
        'HOST': env.get(prefix + 'HOST', '127.0.0.1'),
        'PORT': env.get(prefix + 'PORT', '3306'),
        'OPTIONS': {'charset': 'utf8mb4', 'connect_timeout': 10},
    }


def database_config(env, base_dir):
    # Integration URL wins over legacy DB_ENGINE, but rollback can remove the
    # URL and restore the original DB_* settings explicitly.
    if env.get('DATABASE_URL'):
        return postgres_url_config(env['DATABASE_URL'])
    engine = env.get('DB_ENGINE', '').lower()
    if engine == 'mysql':
        return mysql_config(env)
    if engine in {'postgres', 'postgresql'}:
        config = {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': env.get('DB_NAME', 'financial_dashboard'),
            'USER': env.get('DB_USER', 'postgres'),
            'PASSWORD': env.get('DB_PASSWORD', ''),
            'HOST': env.get('DB_HOST', '127.0.0.1'),
            'PORT': env.get('DB_PORT', '5432'),
            'CONN_MAX_AGE': 0,
            'CONN_HEALTH_CHECKS': True,
            'DISABLE_SERVER_SIDE_CURSORS': True,
            'OPTIONS': {'connect_timeout': 10},
        }
        if env.get('VERCEL'):
            config['OPTIONS']['sslmode'] = 'require'
        return config
    if engine not in {'', 'sqlite', 'sqlite3'}:
        raise ImproperlyConfigured('Unsupported DB_ENGINE.')
    if env.get('VERCEL'):
        raise ImproperlyConfigured(
            'Vercel requires an explicit persistent database; SQLite fallback is disabled.'
        )
    return {'ENGINE': 'django.db.backends.sqlite3', 'NAME': base_dir / 'db.sqlite3'}
