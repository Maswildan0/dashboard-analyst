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
        # Revenue categories are stored uppercase; normalising the requested
        # type lets hand-written links work too (?type=ntf_project).
        self.type_values = [t.upper() for t in _str_list(
            [t for t in (revenue_types or []) if str(t) not in ('', 'Semua', 'all', 'Semua Revenue')])]
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


# ---------------------------------------------------------------------------
# Deep links into the revenue tables (card = slicer).
#
# The Revenue Overview (/dashboard/) exposes its own filter allowlists whose
# values do NOT all exist in the finance master data. Translating them here —
# and validating every value — keeps a card from ever opening an empty page,
# and gives the template the same value maps so the client can rebuild the
# links after an in-place filter apply.
# ---------------------------------------------------------------------------
def revenue_value_maps(years=(), direktorat=(), pp_codes=(), tipe_values=()):
    """{dimension -> {overview value -> revenue query value(s) or None}}.

    A value maps to a LIST because one overview option can cover several
    revenue categories (Overview 'Tipe' NTF = NTF Project + NTF Research).
    None means the overview value has no counterpart in the finance master
    data (or is the "Semua" reset value), so it must be dropped instead of
    being sent to a table that would then render nothing.
    """
    valid_years = {int(v) for v in FinancialPeriod.objects.values_list('year', flat=True).distinct()}
    organizations = {}
    for pk, code, name in OrganizationUnit.objects.filter(is_active=True).values_list('pk', 'code', 'name'):
        for key in (code, name):
            if key:
                organizations.setdefault(str(key).strip().lower(), pk)
    valid_pps = {str(v).strip().lower() for v in PPMaster.objects.filter(is_active=True).values_list('pp_code', flat=True)}
    valid_types = set(RevenueCategory.objects.filter(is_active=True).values_list('code', flat=True))

    # The Overview 'Tipe' filter splits revenue into TF vs NTF (the same split
    # as the composition pie); NTF covers both NTF categories.
    type_codes = {'TF': ['TF'], 'NTF': ['NTF_PROJECT', 'NTF_RESEARCH']}

    def as_year(value):
        try:
            year = int(value)
        except (TypeError, ValueError):
            return None
        return year if year in valid_years else None

    def as_organization(value):
        pk = organizations.get(str(value or '').strip().lower())
        return [pk] if pk is not None else None

    def as_pp(value):
        raw = str(value or '').strip()
        return [raw] if raw.lower() in valid_pps else None

    def as_types(value):
        codes = type_codes.get(str(value or '').strip().upper())
        if not codes:
            return None
        matched = [c for c in codes if c in valid_types]
        return matched or None

    # Keys mirror the Revenue Overview filter names (dashboard.views.
    # _dashboard_filters) so a value map is looked up by the same name.
    return {
        'tahun': {v: as_year(v) for v in years},
        'direktorat': {v: as_organization(v) for v in direktorat},
        'kodePP': {v: as_pp(v) for v in pp_codes},
        'tipe': {v: as_types(v) for v in tipe_values},
    }


def revenue_detail_params(filters=None, period=None, value_maps=None):
    """Query params ({name: [values]}) carrying Revenue Overview state.

    filters: overview filters {'tipe','direktorat','kodePP','tahun'}
    period:  (year, month) the overview cards summarise; the month is always
             carried, the year is the fallback when 'tahun' is not a real
             period year.
    Param order is canonical (tahun, bulan, org, pp, jenis) so the links are
    identical to the ones the client rebuilds from the same filter state.
    """
    f = filters or {}
    maps = value_maps or revenue_value_maps(
        years=[f.get('tahun')],
        direktorat=[f.get('direktorat')],
        pp_codes=[f.get('kodePP')],
        tipe_values=[f.get('tipe')],
    )
    params = {}
    year = maps['tahun'].get(f.get('tahun'))
    if year is None and period is not None:
        year = int(period[0])
    if year is not None:
        params[PARAM_YEARS + '[]'] = [year]
    if period is not None:
        params[PARAM_MONTHS + '[]'] = [int(period[1])]
    for dimension, param in (('direktorat', PARAM_ORGS), ('kodePP', PARAM_PPS), ('tipe', PARAM_TYPES)):
        values = maps.get(dimension, {}).get(f.get(dimension))
        if values:
            params[param + '[]'] = list(values)
    return params


def build_revenue_detail_url(route, params=None):
    """`route` reversed + `params` (as built by revenue_detail_params)."""
    from django.urls import reverse
    from urllib.parse import urlencode
    path = reverse(route)
    query = urlencode(params or {}, doseq=True)
    return f'{path}?{query}' if query else path
