from django.apps import AppConfig


class FinanceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'finance'

    def ready(self):
        # Serverless (Vercel) cold starts run against a fresh DB; ensure the
        # schema exists and seed only when the database is EMPTY. No-op on
        # any database that already has finance data, and never runs when
        # Django is being imported by management commands/tests with a
        # dedicated settings module guard below.
        import os
        if not os.environ.get('DJANGO_SETTINGS_MODULE'):
            return
        # Only auto-provision on serverless or when explicitly requested.
        if not os.environ.get('VERCEL') and os.environ.get('AUTO_SEED') != '1':
            return
        try:
            from django.core.management import call_command
            from .models import FinancialSummary
            if not FinancialSummary.objects.exists():
                call_command('migrate', run_syncdb=True, interactive=False, verbosity=0)
                call_command('seed_financial_data', verbosity=0)
        except Exception:
            # Never crash startup because of seeding; the view will show an
            # empty state if the DB is genuinely unavailable.
            pass
