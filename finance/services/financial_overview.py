"""
Financial Performance Overview canonical figures.

ONE source path per metric, so every card / ratio / chart on the landing
page reconciles with every other and with the database:

    REVENUE ACTUAL   RevenueMonthlySnapshot (CLOSED periods, frozen)
                     + RevenueLedger credit - debit (OPEN periods)
                     scope: period -> PP -> OrganizationUnit -> Campus.
                     Every GL row counts, mapped or not (UNMAPPED included).
    REVENUE TARGET   RevenueBudget + RevenueBudgetMonthly of the ACTIVE
                     RkaVersion, phased per month, summed Jan..selected month.
    KPI TARGET       KpiTarget (campus-specific row wins, else the global row).
    EXPENSE / SHU    No authoritative source exists in this database: the
                     revenue module has no expense ledger, and
                     finance_financialsummary is a generated sample table.
                     These metrics are reported as DATA_NOT_AVAILABLE and
                     rendered as N/A they are NEVER replaced by a placeholder.

Every figure is a Decimal; the frontend only formats. The filters (year,
month, campus, organization) scope literally every value returned here.

Period semantics (brief #4): a summary figure is YTD January..selected month;
the trend series are MONTHLY ACTUALS of the selected year up to that month
(never YTD-cumulative).
"""
import logging
from decimal import Decimal

from django.db.models import Sum

from finance.models import (
    FinancialPeriod,
    KpiTarget,
    RevenueBudget,
    RevenueBudgetMonthly,
    RevenueLedger,
    RevenueMonthlySnapshot,
)

from .financial_metrics import calculate_revenue_achievement, calculate_yoy_growth
from .formatters import format_percent, format_rupiah_compact, format_signed_percent

logger = logging.getLogger(__name__)

ZERO = Decimal('0')
MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun',
              'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']
MONTH_NAMES = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
               'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember']

# Emitted in `warnings` (and logged) whenever a metric has no authoritative
# source for the selected scope.
DATA_NOT_AVAILABLE = 'DATA_NOT_AVAILABLE'

_EXPENSE_REASON = (
    'no authoritative expense source: the revenue module has no expense '
    'ledger and finance_financialsummary is a generated sample table'
)


# ---------------------------------------------------------------------------
# Revenue actual: frozen snapshots for closed months, live GL for open months.
# ---------------------------------------------------------------------------
def _pp_scope(qs, campus=None, organization=None, prefix='pp'):
    """Restrict a PP-bearing queryset to a campus / organization selection."""
    if campus is not None:
        qs = qs.filter(**{f'{prefix}__organization_unit__campus': campus})
    if organization is not None:
        qs = qs.filter(**{f'{prefix}__organization_unit': organization})
    return qs


def _net(credit, debit):
    """SIMKUG revenue convention credit - debit (mirrors revenue_service)."""
    return (credit or ZERO) - (debit or ZERO)


def revenue_by_month(year, months, campus=None, organization=None):
    """{month: Decimal net revenue} for `months` of `year`.

    Exactly two aggregate queries per call: one over the frozen
    RevenueMonthlySnapshot rows of the closed periods, one over the GL rows of
    the open periods. A month without a FinancialPeriod row is absent.
    """
    out = {}
    periods = list(FinancialPeriod.objects.filter(year=year, month__in=list(months)))
    closed = [p.pk for p in periods if p.is_closed]
    open_ = [p.pk for p in periods if not p.is_closed]

    if closed:
        qs = _pp_scope(RevenueMonthlySnapshot.objects.filter(period_id__in=closed),
                       campus, organization)
        for row in qs.values('period__month').annotate(total=Sum('actual_amount')):
            out[row['period__month']] = row['total'] or ZERO
    if open_:
        qs = _pp_scope(RevenueLedger.objects.filter(period_id__in=open_),
                       campus, organization)
        for row in qs.values('period__month').annotate(credit=Sum('credit'), debit=Sum('debit')):
            out[row['period__month']] = _net(row['credit'], row['debit'])
    return out


# ---------------------------------------------------------------------------
# Revenue target (RKA): active RkaVersion, monthly phasing.
# ---------------------------------------------------------------------------
def _budget_scope(qs, campus=None, organization=None, on_budget=False):
    """Restrict a budget queryset to a campus / organization.

    `on_budget` says whether `qs` already is the RevenueBudget queryset (then
    `pp` is a direct field) or the RevenueBudgetMonthly one (then `pp` is
    reached through `revenue_budget`).
    """
    path = 'pp' if on_budget else 'revenue_budget__pp'
    if campus is not None:
        qs = qs.filter(**{f'{path}__organization_unit__campus': campus})
    if organization is not None:
        qs = qs.filter(**{f'{path}__organization_unit': organization})
    return qs


def rka_by_month(year, campus=None, organization=None):
    """{month: Decimal RKA} for the ACTIVE RKA version of `year`.

    A budget row without phasing rows contributes its flat 1/12 share (the
    same fallback the revenue module uses) instead of being dropped.
    """
    out = {m: ZERO for m in range(1, 13)}
    qs = _budget_scope(
        RevenueBudgetMonthly.objects.filter(
            revenue_budget__year=year, revenue_budget__rka_version__is_active=True),
        campus, organization,
    )
    for row in qs.values('month').annotate(total=Sum('budget_amount')):
        if 1 <= row['month'] <= 12:
            out[row['month']] = row['total'] or ZERO

    unphased = _budget_scope(
        RevenueBudget.objects.filter(
            year=year, rka_version__is_active=True, monthly_rows__isnull=True),
        campus, organization, on_budget=True,
    )
    for annual in unphased.values_list('annual_budget', flat=True):
        share = (annual or ZERO) / Decimal('12')
        for month in out:
            out[month] += share
    return out


def rka_ytd(year, month, campus=None, organization=None):
    """RKA January..selected month (never the full annual budget)."""
    by_month = rka_by_month(year, campus, organization)
    return sum((by_month.get(m, ZERO) for m in range(1, month + 1)), ZERO)


# ---------------------------------------------------------------------------
# Revenue actual split by revenue category (TF / NTF_PROJECT / NTF_RESEARCH).
# Used by the Revenue Overview composition panel so it reports the SAME
# actual figures as this page, from the same source.
# ---------------------------------------------------------------------------
def rka_by_category_ytd(year, month, campus=None, organization=None):
    """{category_code: Decimal RKA} for January..selected month.

    RKA is booked per revenue account; the category comes from that account.
    """
    qs = _budget_scope(
        RevenueBudgetMonthly.objects.filter(
            revenue_budget__year=year,
            revenue_budget__rka_version__is_active=True,
            month__lte=month),
        campus, organization,
    )
    out = {}
    for row in qs.values('revenue_budget__revenue_account__revenue_category__code').annotate(
            total=Sum('budget_amount')):
        code = row['revenue_budget__revenue_account__revenue_category__code']
        if code:
            out[code] = out.get(code, ZERO) + (row['total'] or ZERO)
    return out


def revenue_by_category_ytd(year, month, campus=None, organization=None):
    """{category_code: Decimal actual} for January..selected month."""
    months = range(1, month + 1)
    periods = list(FinancialPeriod.objects.filter(year=year, month__in=months))
    closed = [p.pk for p in periods if p.is_closed]
    open_ = [p.pk for p in periods if not p.is_closed]
    out = {}

    if closed:
        qs = _pp_scope(
            RevenueMonthlySnapshot.objects.filter(period_id__in=closed),
            campus, organization,
        )
        for row in qs.values('revenue_account__revenue_category__code').annotate(
                total=Sum('actual_amount')):
            code = row['revenue_account__revenue_category__code']
            if code:
                out[code] = out.get(code, ZERO) + (row['total'] or ZERO)
    if open_:
        qs = _pp_scope(
            RevenueLedger.objects.filter(period_id__in=open_),
            campus, organization,
        )
        for row in qs.values('revenue_account__revenue_category__code').annotate(
                credit=Sum('credit'), debit=Sum('debit')):
            code = row['revenue_account__revenue_category__code']
            if code:
                out[code] = out.get(code, ZERO) + _net(row['credit'], row['debit'])
    return out


# ---------------------------------------------------------------------------
# KPI targets
# ---------------------------------------------------------------------------
def kpi_target(year, kpi_code, campus=None):
    """KpiTarget value, or None when the row does not exist."""
    qs = KpiTarget.objects.filter(year=year, kpi_code=kpi_code)
    if campus is not None:
        scoped = qs.filter(campus=campus).first()
        if scoped is not None:
            return scoped.target_value
    row = qs.filter(campus__isnull=True).first()
    return row.target_value if row else None


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def _unavailable(metric, reason):
    return {'code': DATA_NOT_AVAILABLE, 'metric': metric, 'reason': reason}


def build_financial_overview(year, month, campus=None, organization=None):
    """Canonical Financial Performance Overview payload.

    Every card, ratio and chart on the page is rendered from this dict, so
    they cannot disagree with each other or with the database.

    {
      'period':   {year, month, month_name, is_closed, ytd_label},
      'revenue':  {actual_ytd, rka_ytd, achievement, yoy, available},
      'expense':  {actual_ytd, budget_ytd, utilization, yoy, available},
      'shu':      {actual_ytd, target_ytd, achievement, margin, yoy, available},
      'operating_ratio': {actual, target, achievement, available},
      'shu_margin':      {actual, target, achievement, available},
      'trend':    {months, labels, revenue, rka, expense, shu},
      'warnings': [{code, metric, reason}],
    }
    """
    period = FinancialPeriod.objects.filter(year=year, month=month).first()
    ytd_months = list(range(1, month + 1))

    # Revenue actual: every month of the selected year (trend) + YTD sum, and
    # the same window of the previous year for the YoY comparison.
    revenue_months = revenue_by_month(year, range(1, 13), campus, organization)
    prev_revenue_months = revenue_by_month(year - 1, ytd_months, campus, organization)
    rka_months = rka_by_month(year, campus, organization)

    revenue_actual = sum((revenue_months.get(m, ZERO) for m in ytd_months), ZERO)
    prev_revenue_actual = sum(prev_revenue_months.values(), ZERO)
    revenue_rka = sum((rka_months.get(m, ZERO) for m in ytd_months), ZERO)

    # Trend: months of the selected year that exist as a FinancialPeriod, up
    # to and including the selected month.
    trend_periods = list(
        FinancialPeriod.objects.filter(year=year, month__lte=month).order_by('month')
    )
    trend_months = [p.month for p in trend_periods]

    revenue = {
        'actual_ytd': revenue_actual,
        'rka_ytd': revenue_rka,
        'prev_year_ytd': prev_revenue_actual,
        'achievement': calculate_revenue_achievement(revenue_actual, revenue_rka),
        'yoy': calculate_yoy_growth(revenue_actual, prev_revenue_actual),
        'available': True,
    }

    # Expense / SHU: no authoritative source (see module docstring).
    expense = {
        'actual_ytd': None, 'budget_ytd': None, 'utilization': None,
        'yoy': None, 'available': False,
    }
    shu = {
        'actual_ytd': None, 'target_ytd': None, 'achievement': None,
        'margin': None, 'yoy': None, 'available': False,
    }

    # Targets come from the database; the ratios themselves need expense.
    or_target = kpi_target(year, 'OPERATING_RATIO', campus)
    margin_target = kpi_target(year, 'SHU_MARGIN', campus)
    operating_ratio = {
        'actual': None, 'target': or_target, 'achievement': None, 'available': False,
    }
    shu_margin = {
        'actual': None, 'target': margin_target, 'achievement': None, 'available': False,
    }

    warnings = [
        _unavailable('expense_actual', _EXPENSE_REASON),
        _unavailable('expense_budget', _EXPENSE_REASON),
        _unavailable('shu_actual', _EXPENSE_REASON),
        _unavailable('shu_target', _EXPENSE_REASON),
        _unavailable('operating_ratio', _EXPENSE_REASON),
        _unavailable('shu_margin', _EXPENSE_REASON),
    ]
    for warning in warnings:
        logger.warning(
            '%s metric=%s year=%s month=%s campus=%s organization=%s: %s',
            DATA_NOT_AVAILABLE, warning['metric'], year, month,
            campus.code if campus else 'ALL',
            organization.code if organization else 'ALL',
            warning['reason'],
        )

    return {
        'period': {
            'year': year,
            'month': month,
            'month_name': MONTH_NAMES[month - 1] if 1 <= month <= 12 else str(month),
            'is_closed': bool(period.is_closed) if period else False,
            'ytd_label': f'Jan-{MONTH_ABBR[month - 1]} {year}' if 1 <= month <= 12 else str(year),
        },
        'filters': {
            'campus': campus.code if campus else 'ALL',
            'organization': organization.code if organization else 'ALL',
        },
        'revenue': revenue,
        'expense': expense,
        'shu': shu,
        'operating_ratio': operating_ratio,
        'shu_margin': shu_margin,
        'trend': {
            'months': trend_months,
            'labels': [MONTH_ABBR[m - 1] for m in trend_months],
            'revenue': [revenue_months.get(m, ZERO) for m in trend_months],
            'rka': [rka_months.get(m, ZERO) for m in trend_months],
            'expense': None,
            'shu': None,
        },
        'warnings': warnings,
    }


# ---------------------------------------------------------------------------
# Presentation helpers the templates consume. Amounts/percentages without a
# source render as N/A, never as a placeholder number.
# ---------------------------------------------------------------------------
NA = 'N/A'


def display_amount(value):
    return NA if value is None else format_rupiah_compact(value)


def display_percent(value):
    return NA if value is None else format_percent(value)


def display_signed(value):
    return NA if value is None else format_signed_percent(value)
