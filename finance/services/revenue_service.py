"""Revenue Overview computations (database-driven).

Every figure traces to source:
- Actual        -> RevenueLedger (debit/credit convention) or frozen
                   RevenueMonthlySnapshot for closed periods.
- Target/RKA    -> RevenueBudget + RevenueBudgetMonthly.
- Category      -> RevenueAccount.revenue_category.
- Organization  -> PPMaster.organization_unit.

Derived numbers (YTD, achievement, variance, YoY, composition) are computed
here never stored as source-of-truth.
"""
from decimal import Decimal
from datetime import date

from django.db.models import Q, Sum

from finance.models import (
    FinancialPeriod,
    RevenueBudget,
    RevenueBudgetMonthly,
    RevenueLedger,
    RevenueMonthlySnapshot,
)

from .revenue_context import RevenueContext, month_name

ZERO = Decimal('0')


def _sign_convention(credit, debit):
    """Configurable revenue convention. SIMKUG assumption: net = credit - debit.
    Swap/negate here once validated by accounting."""
    return credit - debit


def ledger_revenue(ledger_row):
    return _sign_convention(ledger_row.credit, ledger_row.debit)


def _period_scope(ctx, *, closed):
    """FinancialPeriods for YTD reads: same-year <= ctx.month, optionally
    restricted to closed/open so live (open) and frozen (closed) sources never
    double count."""
    return FinancialPeriod.objects.filter(
        year=ctx.year, month__lte=ctx.month, is_closed=closed
    )


def _actual_for_period_qs(period, ctx=None, *, frozen_only=False):
    """Queryset of frozen snapshot (closed) OR ledger rows for one period."""
    base = RevenueLedger.objects.filter(period=period)
    if ctx is not None:
        base = ctx.filter_ledger(base)
    return base


def actual_amount(qs, *, net_field='credit'):
    """Sum net revenue over a queryset using the configured sign convention.

    net_field unused placeholder; real impl sums credit/debit separately so
    the convention applies per-row (a credit of 5 & debit of 2 -> 3, not 7).
    """
    total = ZERO
    for row in qs.only('credit', 'debit').iterator(chunk_size=1000):
        total += _sign_convention(row.credit, row.debit)
    return total


# --------------------------------------------------------------------------
# YTD actual (Jan .. month), reading frozen snapshots for closed months and
# live ledger for the (open) selected month.
# --------------------------------------------------------------------------
def actual_ytd(ctx):
    """Actual revenue Jan..selected month under ctx filters."""
    # Apply ctx filters WITHOUT the single-period restriction (a loop helper).
    def scoped(qs):
        if ctx.category is not None:
            qs = qs.filter(revenue_account__revenue_category=ctx.category)
        elif ctx.revenue_account is not None:
            qs = qs.filter(revenue_account=ctx.revenue_account)
        if ctx.organization is not None:
            qs = qs.filter(pp__organization_unit=ctx.organization)
        if ctx.pp is not None:
            qs = qs.filter(pp=ctx.pp)
        return qs

    total = ZERO
    for period in _period_scope(ctx, closed=True):
        snaps = scoped(RevenueMonthlySnapshot.objects.filter(period=period))
        total += snaps.aggregate(s=Sum('actual_amount'))['s'] or ZERO
    for period in _period_scope(ctx, closed=False):
        total += actual_amount(scoped(RevenueLedger.objects.filter(period=period)))
    return total


def rka_ytd(ctx):
    """RKA Jan..selected month under ctx filters (annual budget phased)."""
    budgets = ctx.filter_budget(RevenueBudget.objects.all())
    total = ZERO
    for b in budgets.select_related('rka_version').filter(rka_version__is_active=True).iterator(chunk_size=500):
        rows = b.monthly_rows.filter(month__lte=ctx.month)
        if not rows.exists():
            # no phasing row => assume flat annual share for months <= ctx.month
            total += (b.annual_budget * Decimal(ctx.month)) / Decimal(12)
            continue
        total += rows.aggregate(s=Sum('budget_amount'))['s'] or ZERO
    return total


# --------------------------------------------------------------------------
# Monthly series for the RKA-vs-Actual chart (Jan..selected month).
# --------------------------------------------------------------------------
def monthly_series(ctx, months=None):
    """[{month, month_name, actual, rka}] for January .. ctx.month."""
    months = months or list(range(1, ctx.month + 1))
    out = []
    # preload budgets grouped by month
    budget_rows = ctx.filter_budget(RevenueBudget.objects.filter(rka_version__is_active=True))
    budget_by_month = {}
    for b in budget_rows.select_related('rka_version').iterator(chunk_size=500):
        mrows = b.monthly_rows.all()
        if mrows.exists():
            for m in mrows:
                budget_by_month[m.month] = budget_by_month.get(m.month, ZERO) + m.budget_amount
        else:
            share = b.annual_budget / Decimal(12)
            for m in range(1, 13):
                budget_by_month[m] = budget_by_month.get(m, ZERO) + share
    for month in months:
        period = FinancialPeriod.objects.filter(year=ctx.year, month=month).first()
        actual = ZERO
        if period is not None:
            if period.is_closed:
                snaps = RevenueMonthlySnapshot.objects.filter(period=period)
                if ctx.category is not None:
                    snaps = snaps.filter(revenue_account__revenue_category=ctx.category)
                elif ctx.revenue_account is not None:
                    snaps = snaps.filter(revenue_account=ctx.revenue_account)
                if ctx.organization is not None:
                    snaps = snaps.filter(pp__organization_unit=ctx.organization)
                if ctx.pp is not None:
                    snaps = snaps.filter(pp=ctx.pp)
                actual = snaps.aggregate(s=Sum('actual_amount'))['s'] or ZERO
            else:
                actual = actual_amount(ctx.filter_ledger(RevenueLedger.objects.filter(period=period)))
        out.append({
            'month': month,
            'month_name': month_name(month),
            'actual': actual,
            'rka': budget_by_month.get(month, ZERO),
        })
    return out


# --------------------------------------------------------------------------
# YoY: selected month actual vs same month previous year.
# --------------------------------------------------------------------------
def yoy_series(ctx):
    """Compare monthly actual ctx.year vs ctx.year-1 for Jan..ctx.month."""
    prev_year = ctx.year - 1
    cur = monthly_series(ctx)
    prev_ctx = RevenueContext(year=prev_year, month=ctx.month,
                              revenue_type=ctx.revenue_type,
                              organization_id=ctx.organization.pk if ctx.organization else None,
                              pp_code=ctx.pp.pp_code if ctx.pp else None,
                              account_code=ctx.revenue_account.account_code if ctx.revenue_account else None)
    prev = {m['month']: m['actual'] for m in monthly_series(prev_ctx)}
    out = []
    for m in cur:
        p = prev.get(m['month'], ZERO)
        growth = None
        if p:
            growth = ((m['actual'] - p) / p) * Decimal(100)
        out.append({**m, 'previous_year': p, 'yoy': growth})
    return out


def _category_actual(ctx, category_code):
    sub = RevenueContext(year=ctx.year, month=ctx.month, revenue_type=category_code,
                         organization_id=ctx.organization.pk if ctx.organization else None,
                         pp_code=ctx.pp.pp_code if ctx.pp else None)
    return actual_ytd(sub) if False else _actual_period_total(sub)


def _actual_period_total(ctx):
    """Actual for the selected month only."""
    if ctx.period is None:
        return ZERO
    if ctx.period.is_closed:
        snaps = RevenueMonthlySnapshot.objects.filter(period=ctx.period)
        if ctx.category is not None:
            snaps = snaps.filter(revenue_account__revenue_category=ctx.category)
        elif ctx.revenue_account is not None:
            snaps = snaps.filter(revenue_account=ctx.revenue_account)
        if ctx.organization is not None:
            snaps = snaps.filter(pp__organization_unit=ctx.organization)
        if ctx.pp is not None:
            snaps = snaps.filter(pp=ctx.pp)
        return snaps.aggregate(s=Sum('actual_amount'))['s'] or ZERO
    return actual_amount(ctx.filter_ledger(RevenueLedger.objects.filter(period=ctx.period)))


def composition(ctx):
    """TF / NTF_PROJECT / NTF_RESEARCH actual share (YTD). Values + pct."""
    codes = ['TF', 'NTF_PROJECT', 'NTF_RESEARCH']
    totals = {}
    for code in codes:
        sub = RevenueContext(year=ctx.year, month=ctx.month, revenue_type=code,
                             organization_id=ctx.organization.pk if ctx.organization else None,
                             pp_code=ctx.pp.pp_code if ctx.pp else None,
                             account_code=ctx.revenue_account.account_code if ctx.revenue_account else None)
        totals[code] = actual_ytd(sub)
    grand = sum(totals.values(), ZERO)
    result = {}
    for code in codes:
        pct = (totals[code] / grand * Decimal(100)) if grand else ZERO
        result[code] = {'actual': totals[code], 'pct': pct}
    result['total'] = grand
    return result


def org_pp_performance(ctx):
    """Actual YTD + RKA YTD grouped by organization, then by PP.

    Returns {'orgs': [{name, actual, rka}], 'pps': [{org, pp_code, actual, rka}]}.
    Only includes rows touching ctx filters (category/account etc.).
    """
    # actual by pp (only pp-mapped rows)
    actual_rows = ctx.filter_ledger(RevenueLedger.objects.filter(
        period__year=ctx.year, period__month__lte=ctx.month, pp__isnull=False,
    ))
    if ctx.period is None or not ctx.period.is_closed:
        pass
    actual_by_pp = {}
    for row in actual_rows.select_related('pp__organization_unit').only('pp_id', 'credit', 'debit', 'pp__organization_unit_id').iterator(chunk_size=1000):
        actual_by_pp[row.pp_id] = actual_by_pp.get(row.pp_id, ZERO) + _sign_convention(row.credit, row.debit)

    # rka by pp
    rka_by_pp = {}
    budgets = ctx.filter_budget(RevenueBudget.objects.filter(rka_version__is_active=True))
    for b in budgets.select_related('pp__organization_unit').iterator(chunk_size=500):
        mrows = b.monthly_rows.filter(month__lte=ctx.month)
        amount = (mrows.aggregate(s=Sum('budget_amount'))['s'] or ZERO) if mrows.exists() else \
            b.annual_budget * Decimal(ctx.month) / Decimal(12)
        rka_by_pp[b.pp_id] = rka_by_pp.get(b.pp_id, ZERO) + amount

    from finance.models import PPMaster
    pps = PPMaster.objects.filter(is_active=True).select_related('organization_unit')
    if ctx.organization is not None:
        pps = pps.filter(organization_unit=ctx.organization)
    if ctx.pp is not None:
        pps = pps.filter(pk=ctx.pp.pk)

    org_rows = {}
    pp_rows = []
    for pp in pps:
        a = actual_by_pp.get(pp.pk, ZERO)
        r = rka_by_pp.get(pp.pk, ZERO)
        org_name = pp.organization_unit.name if pp.organization_unit else ''
        oa, ork = org_rows.get(org_name, (ZERO, ZERO))
        org_rows[org_name] = (oa + a, ork + r)
        pp_rows.append({'pp_code': pp.pp_code, 'org': org_name, 'actual': a, 'rka': r})

    orgs = [{'name': k, 'actual': v[0], 'rka': v[1]} for k, v in sorted(org_rows.items())]
    return {'orgs': orgs, 'pps': pp_rows}
