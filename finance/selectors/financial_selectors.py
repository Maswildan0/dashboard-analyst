"""
Data selectors — optimized read paths for the dashboard.

Single aggregate queries instead of per-card queries (#71). Returns plain
dicts with Decimals so the service layer can compute KPIs.
"""

from decimal import Decimal

from django.db.models import Sum

from finance.models import Campus, FinancialPeriod, FinancialSummary, KpiTarget, OrganizationUnit, RevenueTransactionSummary

ZERO = Decimal('0')


def get_latest_period():
    """Most recent period with data (default filter, #5)."""
    return FinancialPeriod.objects.filter(summaries__isnull=False).order_by('-year', '-month').first()


def get_period(year, month):
    try:
        return FinancialPeriod.objects.get(year=year, month=month)
    except FinancialPeriod.DoesNotExist:
        return None


def get_previous_year_period(period):
    """Same month, previous year. Returns None when year-1 has no period."""
    return get_period(period.year - 1, period.month)


def get_campus(code=None):
    if code is None or code in ('', 'all', 'Semua'):
        return None
    return Campus.objects.filter(code=code, is_active=True).first()


def list_campuses():
    return list(Campus.objects.filter(is_active=True).order_by('code'))


def list_org_units(campus=None):
    qs = OrganizationUnit.objects.filter(is_active=True)
    if campus:
        qs = qs.filter(campus=campus)
    return list(qs.order_by('code'))


def get_financial_summary(period, campus, organization_unit=None):
    """Single-row (period, campus, unit) summary, or None."""
    qs = FinancialSummary.objects.filter(period=period, campus=campus)
    if organization_unit:
        qs = qs.filter(organization_unit=organization_unit)
    else:
        qs = qs.filter(organization_unit__isnull=True)
    return qs.first()


def get_previous_summary(previous_period, campus, organization_unit=None):
    if previous_period is None:
        return None
    return get_financial_summary(previous_period, campus, organization_unit)


def get_revenue_by_category(period, campus, organization_unit=None):
    """{category_code: {'actual': Decimal, 'target': Decimal}} via one query."""
    qs = RevenueTransactionSummary.objects.filter(period=period, campus=campus)
    if organization_unit:
        qs = qs.filter(organization_unit=organization_unit)
    else:
        qs = qs.filter(organization_unit__isnull=True)
    rows = qs.values('revenue_category__code').annotate(
        actual=Sum('actual_amount'),
        target=Sum('target_amount'),
    )
    return {r['revenue_category__code']: {'actual': r['actual'] or ZERO, 'target': r['target'] or ZERO} for r in rows}


def get_previous_revenue_by_category(previous_period, campus, organization_unit=None):
    if previous_period is None:
        return {}
    return get_revenue_by_category(previous_period, campus, organization_unit)


def get_kpi_target(year, kpi_code, campus=None):
    qs = KpiTarget.objects.filter(year=year, kpi_code=kpi_code)
    if campus:
        # Prefer campus-specific; fall back to the global (campus=None) target.
        specific = qs.filter(campus=campus).first()
        if specific is not None:
            return specific.target_value
    qs = qs.filter(campus__isnull=True)
    target = qs.first()
    return target.target_value if target else None


def get_trend(year, campus, organization_unit=None):
    """All months of `year` for (campus, unit): [{month, revenue, expense, shu}]."""
    period_ids = FinancialPeriod.objects.filter(year=year).values_list('id', flat=True)
    qs = FinancialSummary.objects.filter(period_id__in=period_ids, campus=campus)
    if organization_unit:
        qs = qs.filter(organization_unit=organization_unit)
    else:
        qs = qs.filter(organization_unit__isnull=True)
    rows = qs.values('period__month').annotate(
        revenue=Sum('revenue_actual'),
        expense=Sum('expense_actual'),
        shu=Sum('shu_actual'),
    )
    by_month = {r['period__month']: r for r in rows}
    out = []
    for m in range(1, 13):
        r = by_month.get(m)
        out.append({
            'month': m,
            'revenue': (r['revenue'] if r else ZERO),
            'expense': (r['expense'] if r else ZERO),
            'shu': (r['shu'] if r else ZERO),
        })
    return out
