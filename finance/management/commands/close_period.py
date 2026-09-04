"""Close a revenue period (freeze monthly + project snapshots).

Run: python manage.py close_period --year 2026 --month 8 [--force]
"""
from django.core.management.base import BaseCommand
from finance.models import FinancialPeriod
from finance.services.closing_service import close_revenue_period


class Command(BaseCommand):
    help = 'Close a financial period: freeze monthly + project revenue snapshots.'

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, required=True)
        parser.add_argument('--month', type=int, required=True)
        parser.add_argument('--force', action='store_true')

    def handle(self, *args, **opts):
        period = FinancialPeriod.objects.filter(year=opts['year'], month=opts['month']).first()
        if period is None:
            self.stderr.write(f'period {opts["year"]}-{opts["month"]:02d} not found')
            return
        result = close_revenue_period(period, force=opts['force'])
        self.stdout.write(self.style.SUCCESS(str(result)))
