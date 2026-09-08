"""Shared Revenue filter context (multi-select aware).

Every Revenue Overview component (KPI, composition, monthly series, YoY,
organization/PP performance) must be built from the SAME context so all
numbers agree. Filters accept MULTIPLE values per dimension:
  years / months / revenue_types / organizations / pps / accounts
A page may choose the FIRST period (single "selected period" semantics) or
iterate every selected period (multi-period rows) via .periods.
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

# Query-string parameter names used by the revenue table filters.
PARAM_YEARS = 'tahun'
PARAM_MONTHS = 'bulan'
PARAM_TYPES = 'jenis'
PARAM_ORGS = 'org'
PARAM_PPS = 'pp'
PARAM_ACCOUNTS = 'account'


def _int_list(values):
    out = []
    for v in values:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


def _str_list(values, exclude=None):
    out = []
    for v in values:
        v = '' if v is None else str(v).strip()
        if not v:
            continue
        if exclude and v in exclude:
            continue
        out.append(v)
    return out


def _first_int(values, default=None):
    try:
        return int(values[0]) if values else default
    except (TypeError, ValueError):
        return default


def month_name(month):
    return MONTH_NAMES[month - 1] if 1 <= month <= 12 else str(month)


class RevenueContext:
    """Resolved multi-value filter context.

    Lists hold the raw requested values; resolved models are available on
    the *objects attributes (organizations, pps, accounts, categories).
    Single-value conveniences (year/month/revenue_type/organization/pp/
    revenue_account) default to the FIRST selected value so existing
    single-period services keep working unchanged.
    """

    def __init__(self, request=None, *, years=None, months=None,
                 revenue_types=None, organization_ids=None, pp_codes=None,
                 account_codes=None,
                 # legacy single-value kwargs (backward compatible)
                 year=None, month=None, revenue_type=None,
                 organization_id=None, pp_code=None, account_code=None):
        # ---- translate legacy single-value kwargs to lists ----
        if years is None and year is not None:
            years = [year]
        if months is None and month is not None:
            months = [month]
        if revenue_types is None and revenue_type is not None:
            revenue_types = [revenue_type]
        if organization_ids is None and organization_id is not None:
            organization_ids = [organization_id]
        if pp_codes is None and pp_code is not None:
            pp_codes = [pp_code]
        if account_codes is None and account_code is not None:
            account_codes = [account_code]
        # ---- years / months (multi) ----
        if request is not None:
            years = years if years is not None else (request.GET.getlist(PARAM_YEARS) or request.GET.getlist(PARAM_YEARS + '[]'))
            months = months if months is not None else (request.GET.getlist(PARAM_MONTHS) or request.GET.getlist(PARAM_MONTHS + '[]'))
            revenue_types = revenue_types if revenue_types is not None else (request.GET.getlist(PARAM_TYPES) or request.GET.getlist(PARAM_TYPES + '[]'))
            organization_ids = organization_ids if organization_ids is not None else (request.GET.getlist(PARAM_ORGS) or request.GET.getlist(PARAM_ORGS + '[]'))
            pp_codes = pp_codes if pp_codes is not None else (request.GET.getlist(PARAM_PPS) or request.GET.getlist(PARAM_PPS + '[]'))
            account_codes = account_codes if account_codes is not None else (request.GET.getlist(PARAM_ACCOUNTS) or request.GET.getlist(PARAM_ACCOUNTS + '[]'))
            # Backward compatibility: accept legacy single-value params
            # (?year=&month=&type=&org=&pp=&account=) when no [] list sent.
            if not years:
                _y = request.GET.get('year')
                if _y:
                    years = [_y]
            if not months:
                _m = request.GET.get('month')
                if _m:
                    months = [_m]
            if not revenue_types:
                _t = request.GET.get('type')
                if _t:
                    revenue_types = [_t]
            if not organization_ids:
                _o = request.GET.get('org')
                if _o:
                    organization_ids = [_o]
            if not pp_codes:
                _p = request.GET.get('pp')
                if _p:
                    pp_codes = [_p]
            if not account_codes:
                _a = request.GET.get('account')
                if _a:
                    account_codes = [_a]
        elif years is None:
            years = []

        # normalize 'Semua'/'all' -> empty (no constraint)
        self.year_values = _int_list([y for y in years if str(y) not in ('', 'Semua', 'all')])
        self.month_values = _int_list([m for m in months if str(m) not in ('', 'Semua', 'all')])
        self.type_values = _str_list(
            [t for t in (revenue_types or []) if str(t) not in ('', 'Semua', 'all', 'Semua Revenue')])
        self.org_values = _str_list(
            [o for o in (organization_ids or []) if str(o) not in ('', 'Semua', 'all', 'Semua Organization')])
        self.pp_values = _str_list(
            [p for p in (pp_codes or []) if str(p) not in ('', 'Semua', 'all', 'Semua PP')])
        self.account_values = _str_list(
            [a for a in (account_codes or []) if str(a) not in ('', 'Semua', 'all', 'Semua Akun')])

        # ---- default to latest available period when nothing selected ----
        latest = FinancialPeriod.objects.order_by('-year', '-month').first()
        if not self.year_values:
            self.year_values = [latest.year] if latest else [date.today().year]
        if not self.month_values:
            self.month_values = [latest.month] if latest else [date.today().month]

        self.year = self.year_values[0]
        self.month = self.month_values[0]

        # ---- resolved objects (multi) ----
        self.categories = list(RevenueCategory.objects.filter(
            code__in=self.type_values, is_active=True)) if self.type_values else []
        org_qs = OrganizationUnit.objects.filter(is_active=True)
        self.organizations = list(org_qs.filter(code__in=self.org_values)) if self.org_values else []
        # org by pk OR code — org_values may carry either; resolve both ways
        if self.org_values and not self.organizations:
            for v in self.org_values:
                if str(v).isdigit():
                    obj = org_qs.filter(pk=int(v)).first()
                else:
                    obj = org_qs.filter(code=v).first()
                if obj and obj not in self.organizations:
                    self.organizations.append(obj)
        pp_qs = PPMaster.objects.filter(is_active=True, pp_code__in=self.pp_values) if self.pp_values else PPMaster.objects.none()
        if self.organizations:
            pp_qs = pp_qs.filter(organization_unit__in=[o for o in self.organizations])
        self.pps = list(pp_qs)
        # Accounts resolve ONLY from an explicit account filter (never derived
        # from category — legacy services use revenue_account as "user picked
        # this exact account", while category is applied via .categories).
        if self.account_values:
            acc_qs = RevenueAccount.objects.filter(
                is_active=True, account_code__in=self.account_values)
            if self.categories:
                acc_qs = acc_qs.filter(revenue_category__in=[c for c in self.categories])
            self.accounts = list(acc_qs)
        else:
            self.accounts = []

        # ---- first-value conveniences (single-period compatibility) ----
        self.organization = self.organizations[0] if self.organizations else None
        self.pp = self.pps[0] if self.pps else None
        self.revenue_account = self.accounts[0] if self.accounts else None
        self.revenue_type = self.type_values[0] if self.type_values else 'all'
        self.category = self.categories[0] if self.categories else None
        self.period = FinancialPeriod.objects.filter(
            year=self.year, month=self.month).first()

    # ------------------------------------------------------------------
    @property
    def periods(self):
        """All selected (year, month) periods sorted ascending."""
        out = []
        for y in sorted(self.year_values):
            for m in sorted(self.month_values):
                out.append((y, m))
        return out

    @property
    def period_key(self):
        return f'{self.year}-{self.month:02d}'

    # ------------------------------------------------------------------
    def _apply_org_pp(self, qs):
        if self.organizations:
            qs = qs.filter(pp__organization_unit__in=[o for o in self.organizations])
        if self.pps:
            qs = qs.filter(pp__in=[p for p in self.pps])
        return qs

    def filter_ledger(self, qs):
        """Apply this context to a RevenueLedger queryset (actual rows)."""
        if self.period is not None:
            qs = qs.filter(period=self.period)
        if self.accounts:
            qs = qs.filter(revenue_account__in=[a for a in self.accounts])
        elif self.categories:
            qs = qs.filter(revenue_account__revenue_category__in=[c for c in self.categories])
        return self._apply_org_pp(qs)

    def filter_budget(self, qs):
        """Apply year + (org/pp/account/category) to RevenueBudget queryset."""
        qs = qs.filter(year__in=self.year_values)
        if self.accounts:
            qs = qs.filter(revenue_account__in=[a for a in self.accounts])
        elif self.categories:
            qs = qs.filter(revenue_account__revenue_category__in=[c for c in self.categories])
        return self._apply_org_pp(qs)

    def month_range_ytd(self):
        """(start_date, end_date) for January .. first selected month."""
        start = date(self.year, 1, 1)
        end = date(self.year, self.month, 28)
        return start, end

    def as_dict(self):
        return {
            'years': self.year_values,
            'months': self.month_values,
            'period_key': self.period_key,
            'revenue_types': self.type_values,
            'organizations': self.organizations,
            'pps': self.pps,
            'accounts': self.accounts,
        }

    def query_args(self):
        """Re-usable query params preserving all selections."""
        args = {}
        for y in self.year_values:
            args.setdefault(PARAM_YEARS + '[]', []).append(y)
        for m in self.month_values:
            args.setdefault(PARAM_MONTHS + '[]', []).append(m)
        for t in self.type_values:
            args.setdefault(PARAM_TYPES + '[]', []).append(t)
        for o in self.organizations:
            args.setdefault(PARAM_ORGS + '[]', []).append(o.pk)
        for p in self.pps:
            args.setdefault(PARAM_PPS + '[]', []).append(p.pp_code)
        for a in self.accounts:
            args.setdefault(PARAM_ACCOUNTS + '[]', []).append(a.account_code)
        return args

    def for_period(self, year, month):
        """A copy of this context pinned to ONE (year, month) period — used by
        list builders to emit one row per selected period. All other filter
        dimensions (org/pp/account/type) are preserved."""
        return RevenueContext(
            years=[year], months=[month],
            revenue_types=self.type_values,
            organization_ids=[str(o.pk) for o in self.organizations],
            pp_codes=[p.pp_code for p in self.pps],
            account_codes=[a.account_code for a in self.accounts],
        )
