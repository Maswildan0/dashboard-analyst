from django.apps import AppConfig


class FinanceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'finance'

    # Startup must never migrate, seed, or connect to a database. Schema and
    # data changes are explicit management operations, including on Vercel.
