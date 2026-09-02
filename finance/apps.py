from django.apps import AppConfig


class FinanceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'finance'

    def ready(self):
        # On serverless (Vercel) the DB is created fresh per cold start in
        # /tmp; run migrate + seed automatically so the landing page always
        # has data. No-op locally once the DB is already migrated/seeded.
        import os
        if not os.environ.get('DJANGO_SETTINGS_MODULE'):
            return
        try:
            from django.core.management import call_command
            from django.db import connection
            call_command('migrate', run_syncdb=True, interactive=False, verbosity=0)
            from .models import FinancialSummary
            if not FinancialSummary.objects.exists():
                call_command('seed_financial_data', verbosity=0)
        except Exception:
            # Never crash startup because of seeding; the view will show an
            # empty state if the DB is genuinely unavailable.
            pass
