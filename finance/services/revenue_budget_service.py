"""RKA budget aggregation and phasing validation.

No redundant tables: per-PP / per-account / per-org / total RKA are all
derived from the base grain (RevenueBudget + RevenueBudgetMonthly).
"""
from decimal import Decimal

from django.db.models import Sum

from finance.models import RevenueBudget, RevenueBudgetMonthly

ZERO = Decimal('0')


def annual_sum(version_id=None, year=None, pp=None, account=None, org=None):
    qs = RevenueBudget.objects.all()
    if version_id is not None:
        qs = qs.filter(rka_version_id=version_id)
    else:
        qs = qs.filter(rka_version__is_active=True)
    if year is not None:
        qs = qs.filter(year=year)
    if pp is not None:
        qs = qs.filter(pp=pp)
    if account is not None:
        qs = qs.filter(revenue_account=account)
    if org is not None:
        qs = qs.filter(pp__organization_unit=org)
    return qs.aggregate(s=Sum('annual_budget'))['s'] or ZERO


def monthly_sum(version_id=None, year=None, pp=None, account=None, org=None, month=None):
    qs = RevenueBudgetMonthly.objects.select_related('revenue_budget')
    if month is not None:
        qs = qs.filter(month=month)
    if version_id is not None:
        qs = qs.filter(revenue_budget__rka_version_id=version_id)
    else:
        qs = qs.filter(revenue_budget__rka_version__is_active=True)
    if year is not None:
        qs = qs.filter(revenue_budget__year=year)
    if pp is not None:
        qs = qs.filter(revenue_budget__pp=pp)
    if account is not None:
        qs = qs.filter(revenue_budget__revenue_account=account)
    if org is not None:
        qs = qs.filter(revenue_budget__pp__organization_unit=org)
    return qs.aggregate(s=Sum('budget_amount'))['s'] or ZERO


def validate_phasing(rka_version):
    """Ensure annual RKA == SUM(monthly phasing) per budget row.

    Returns list of mismatches (never silently fixed):
    [{budget_id, pp, account, annual, phased, diff}]
    """
    mismatches = []
    for b in rka_version.budgets.select_related('pp', 'revenue_account').prefetch_related('monthly_rows'):
        phased = b.monthly_rows.aggregate(s=Sum('budget_amount'))['s'] or ZERO
        if phased != b.annual_budget:
            mismatches.append({
                'budget_id': b.id,
                'pp': b.pp.pp_code if b.pp else None,
                'account': b.revenue_account.account_code,
                'annual': b.annual_budget,
                'phased': phased,
                'diff': b.annual_budget - phased,
            })
    return mismatches


def compare_actual_vs_rka(actual, rka):
    """Variance + achievement; zero-safe."""
    variance = actual - rka
    achievement = (actual / rka * Decimal(100)) if rka else None
    return {
        'variance': variance,
        'achievement': achievement,
        'actual': actual,
        'rka': rka,
    }
