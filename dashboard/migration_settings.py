"""Opt-in settings for read-only source audit; never use for web deployment."""
from .settings import *  # noqa: F403
from .database_config import mysql_config, postgres_url_config

# Require an explicit source name to avoid auditing the wrong local database.
if not os.environ.get('SOURCE_DB_NAME'):
    raise ImproperlyConfigured('Set SOURCE_DB_NAME locally before auditing MySQL.')

DATABASES['source'] = mysql_config(os.environ, 'SOURCE_DB_')
DATABASES['source']['OPTIONS']['isolation_level'] = 'repeatable read'
DATABASE_ROUTERS = ['dashboard.migration_router.SourceReadOnlyRouter']
DEBUG = False

# DDL/data migration should use the direct connection when available.
if os.environ.get('DATABASE_URL_UNPOOLED'):
    DATABASES['default'] = postgres_url_config(os.environ['DATABASE_URL_UNPOOLED'])
