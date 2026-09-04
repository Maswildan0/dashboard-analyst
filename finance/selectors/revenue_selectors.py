"""Filter option queries for the Revenue Overview UI.

Cascading rules (master prompt #31):
- Organization -> limits PP list.
- Revenue Type -> limits Account list.
- PP/Account selections always respect their parents.
"""
from finance.models import (
    OrganizationUnit,
    PPMaster,
    RevenueAccount,
    RevenueCategory,
)


def list_categories():
    return list(RevenueCategory.objects.filter(is_active=True).order_by('code'))


def list_organizations():
    return list(OrganizationUnit.objects.filter(is_active=True).order_by('code'))


def list_pps(organization=None):
    qs = PPMaster.objects.filter(is_active=True)
    if organization is not None:
        qs = qs.filter(organization_unit=organization)
    return list(qs.order_by('pp_code'))


def list_accounts(category=None):
    qs = RevenueAccount.objects.filter(is_active=True)
    if category is not None:
        qs = qs.filter(revenue_category=category)
    return list(qs.order_by('account_code'))


def cascade_options(organization=None, revenue_type=None):
    """All option sets resolved under the current parents (for re-render)."""
    category = None
    if revenue_type and revenue_type not in ('all', 'Semua', ''):
        category = RevenueCategory.objects.filter(code=revenue_type, is_active=True).first()
    return {
        'categories': list_categories(),
        'organizations': list_organizations(),
        'pps': list_pps(organization),
        'accounts': list_accounts(category),
        'category': category,
    }


def period_options():
    """Available years/months from FinancialPeriod."""
    from finance.models import FinancialPeriod
    years = list(FinancialPeriod.objects.order_by('-year').values_list('year', flat=True).distinct())
    months = list(range(1, 13))
    return years, months
