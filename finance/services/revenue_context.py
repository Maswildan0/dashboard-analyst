"""Shared Revenue filter context.

Every Revenue Overview component (KPI, composition, monthly series, YoY,
organization/PP performance) must be built from the SAME context so all
numbers agree. The context carries resolved master objects, so downstream
services only need `.period`, `.year`, `.month`, `.revenue_type`,
`.organization`, `.pp`, `.revenue_account`, `.category`.
"""
from decimal import Decimal
from datetime import date

from finance.models import (
    FinancialPeriod,
    OrganizationUnit,
    PPMaster,
    RevenueAccount,
    RevenueCategory,
)

ZERO = Decimal('0')

MONTH_NAMES = [
    'Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
    'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember',
]


def _first_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class RevenueContext:
    """Immutable-ish resolved filter context."""

    def __init__(self, request=None, *, year=None, month=None,
                 revenue_type=None, organization_id=None, pp_code=None,
                 account_code=None):
        # default: latest available period
        latest = FinancialPeriod.objects.order_by('-year', '-month').first()
        self.year = _first_int(year) or (latest.year if latest else date.today().year)
        self.month = _first_int(month) or (latest.month if latest else date.today().month)

        self.period = FinancialPeriod.objects.filter(year=self.year, month=self.month).first()

        # revenue type: 'all' | category code
        rt = (revenue_type or 'all').strip()
        self.revenue_type = rt if rt in ('all', 'Semua', '') else rt
        self.category = None
        if self.revenue_type != 'all':
            self.category = RevenueCategory.objects.filter(code=self.revenue_type, is_active=True).first()

        # organization (by pk or code/name)
        self.organization = None
        if organization_id not in (None, '', 'all', 'Semua'):
            org_qs = OrganizationUnit.objects.filter(is_active=True)
            if str(organization_id).isdigit():
                self.organization = org_qs.filter(pk=int(organization_id)).first()
            else:
                self.organization = org_qs.filter(code=organization_id).first() or \
                    org_qs.filter(name=organization_id).first()

        # pp
        self.pp = None
        if pp_code not in (None, '', 'all', 'Semua'):
            qs = PPMaster.objects.filter(is_active=True, pp_code=pp_code)
            if self.organization is not None:
                qs = qs.filter(organization_unit=self.organization)
            self.pp = qs.first()

        # revenue account
        self.revenue_account = None
        if account_code not in (None, '', 'all', 'Semua'):
            qs = RevenueAccount.objects.filter(is_active=True, account_code=account_code)
            if self.category is not None:
                qs = qs.filter(revenue_category=self.category)
            self.revenue_account = qs.first()

    @property
    def period_key(self):
        return f'{self.year}-{self.month:02d}'

    def filter_ledger(self, qs):
        """Apply this context to a RevenueLedger queryset (actual rows)."""
        if self.period is not None:
            qs = qs.filter(period=self.period)
        if self.revenue_account is not None:
            qs = qs.filter(revenue_account=self.revenue_account)
        elif self.category is not None:
            qs = qs.filter(revenue_account__revenue_category=self.category)
        if self.organization is not None:
            qs = qs.filter(pp__organization_unit=self.organization)
        if self.pp is not None:
            qs = qs.filter(pp=self.pp)
        return qs

    def filter_budget(self, qs):
        """Apply year + (org/pp/account/category) to RevenueBudget queryset."""
        qs = qs.filter(year=self.year)
        if self.revenue_account is not None:
            qs = qs.filter(revenue_account=self.revenue_account)
        elif self.category is not None:
            qs = qs.filter(revenue_account__revenue_category=self.category)
        if self.organization is not None:
            qs = qs.filter(pp__organization_unit=self.organization)
        if self.pp is not None:
            qs = qs.filter(pp=self.pp)
        return qs

    def month_range_ytd(self):
        """(start_date, end_date) for January .. selected month of the year."""
        start = date(self.year, 1, 1)
        end = date(self.year, self.month, 28)  # day ignored; filtered by month
        return start, end

    def as_dict(self):
        return {
            'year': self.year,
            'month': self.month,
            'period_key': self.period_key,
            'revenue_type': self.revenue_type,
            'organization': self.organization,
            'pp': self.pp,
            'revenue_account': self.revenue_account,
        }


def month_name(month):
    return MONTH_NAMES[month - 1] if 1 <= month <= 12 else str(month)
