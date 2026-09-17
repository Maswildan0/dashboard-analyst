"""
Development-only reconciliation of the Financial Performance Overview.

Prints, straight from the database, every figure the page renders for a
selection, so the numbers shown in the UI can be compared line by line:

    python manage.py reconcile_financial_overview --year 2026 --month 8
    python manage.py reconcile_financial_overview --year 2026 --month 8 --campus BDG
    python manage.py reconcile_financial_overview --year 2026 --month 8 --campus BDG --unit DIRECTORATBTP

The command re-runs the canonical service the view uses, so it is the page's
own numbers with no second implementation involved.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from finance.models import Campus, FinancialPeriod, OrganizationUnit, RevenueMonthlySnapshot
from finance.services.financial_overview import build_financial_overview

ZERO = Decimal('0')


class Command(BaseCommand):
    help = 'Print the database figures behind the Financial Performance Overview.'

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int)
        parser.add_argument('--month', type=int)
        parser.add_argument('--campus', help='Campus code (default: all campuses)')
        parser.add_argument('--unit', help='OrganizationUnit code (default: all units)')

    def handle(self, *args, **options):
        latest = FinancialPeriod.objects.order_by('-year', '-month').first()
        if latest is None:
            raise CommandError('No FinancialPeriod rows: nothing to reconcile.')

        year = options['year'] or latest.year
        month = options['month'] or latest.month
        period = FinancialPeriod.objects.filter(year=year, month=month).first()
        if period is None:
            raise CommandError(f'No FinancialPeriod for {year}-{month:02d}.')

        campus = None
        if options['campus']:
            campus = Campus.objects.filter(code=options['campus']).first()
            if campus is None:
                raise CommandError(f'Unknown campus code {options["campus"]!r}.')
        organization = None
        if options['unit']:
            organization = OrganizationUnit.objects.filter(code=options['unit']).first()
            if organization is None:
                raise CommandError(f'Unknown organization code {options["unit"]!r}.')
            if campus is not None and organization.campus_id != campus.pk:
                raise CommandError(
                    f'{organization.code} is not part of campus {campus.code}.')

        data = build_financial_overview(year, month, campus, organization)
        rev, exp, shu = data['revenue'], data['expense'], data['shu']
        or_, margin = data['operating_ratio'], data['shu_margin']

        scope = f"campus={campus.code if campus else 'ALL'} unit={organization.code if organization else 'ALL'}"
        self.stdout.write(f'Financial Performance Overview — {data["period"]["ytd_label"]} ({scope})')
        self.stdout.write(f'period closed: {data["period"]["is_closed"]}')
        self.stdout.write('')
        self.stdout.write('  Revenue Actual YTD   : ' + self._money(rev['actual_ytd']))
        self.stdout.write('  Revenue RKA YTD      : ' + self._money(rev['rka_ytd']))
        self.stdout.write('  Revenue Achievement  : ' + self._pct(rev['achievement']))
        self.stdout.write('  Revenue YoY          : ' + self._signed(rev['yoy']))
        self.stdout.write('  Expense Actual YTD   : ' + self._money(exp['actual_ytd']))
        self.stdout.write('  Expense Budget YTD   : ' + self._money(exp['budget_ytd']))
        self.stdout.write('  Budget Utilization   : ' + self._pct(exp['utilization']))
        self.stdout.write('  SHU Actual YTD       : ' + self._money(shu['actual_ytd']))
        self.stdout.write('  SHU Target YTD       : ' + self._money(shu['target_ytd']))
        self.stdout.write('  SHU Achievement      : ' + self._pct(shu['achievement']))
        self.stdout.write('  Operating Ratio      : ' + self._pct(or_['actual'])
                          + '  target ' + self._pct(or_['target']))
        self.stdout.write('  SHU Margin           : ' + self._pct(margin['actual'])
                          + '  target ' + self._pct(margin['target']))
        self.stdout.write('')
        self.stdout.write('  Trend (monthly actual, Rp Miliar):')
        trend = data['trend']
        self.stdout.write('    months : ' + ' '.join(f'{m:>10}' for m in trend['labels']))
        self.stdout.write('    revenue: ' + ' '.join(
            f'{v / 1_000_000_000:>10,.1f}' for v in trend['revenue']))
        self.stdout.write('    rka    : ' + ' '.join(
            f'{v / 1_000_000_000:>10,.1f}' for v in trend['rka']))
        self.stdout.write('    expense: ' + ('not available' if trend['expense'] is None else ''))
        self.stdout.write('    shu    : ' + ('not available' if trend['shu'] is None else ''))

        # Reconciliation: the YTD card must equal the SUM of the trend months
        # it covers (brief #32, #33).
        ytd_from_trend = sum(
            (trend['revenue'][i] for i, m in enumerate(trend['months']) if m <= month), ZERO)
        self.stdout.write('')
        self.stdout.write('  RECONCILE revenue card vs SUM(trend Jan-selected): '
                          + ('OK' if ytd_from_trend == rev['actual_ytd'] else 'MISMATCH')
                          + f' ({self._money(ytd_from_trend)})')
        snapshot_total = ZERO
        for snap in RevenueMonthlySnapshot.objects.filter(
                period__year=year, period__month__lte=month).values_list('actual_amount', flat=True):
            snapshot_total += snap
        self.stdout.write('  INFO frozen snapshot total (all campuses, closed months only): '
                          + self._money(snapshot_total))
        if data['warnings']:
            self.stdout.write('')
            for warning in data['warnings']:
                self.stdout.write(f'  WARNING {warning["code"]} {warning["metric"]}: {warning["reason"]}')

    @staticmethod
    def _money(value):
        return 'N/A' if value is None else f'{value:>20,.2f}'

    @staticmethod
    def _pct(value):
        return 'N/A' if value is None else f'{value:.2f}%'

    @staticmethod
    def _signed(value):
        return 'N/A' if value is None else f'{value:+.2f}%'
