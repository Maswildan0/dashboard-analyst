"""
Generate sample financial data for 2025 and 2026 (January-August) across
4 campuses (#51).

Rules baked in:
- Revenue > Expense for the majority of periods.
- SHU = Revenue - Expense for sample simplicity.
- TF + NTF Project + NTF Research = Total Revenue.
- YoY growth is emergent: 2026 values are derived from 2025 with growth so
  the landing page YoY (same month, previous year) has real movement.

Run: python manage.py seed_financial_data
"""

import random
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand

from finance.models import (
    Campus,
    FinancialPeriod,
    FinancialSummary,
    KpiTarget,
    OrganizationUnit,
    RevenueCategory,
    RevenueTransactionSummary,
)

# Approximate 2025 base monthly revenue per campus (IDR, in millions).
BASE_REVENUE_2025 = {
    'BDG': 560_000_000_000,
    'JKT': 300_000_000_000,
    'SBY': 170_000_000_000,
    'PWT': 95_000_000_000,
}

MONTH_WEIGHTS = [
    0.82, 0.86, 0.90, 0.95, 1.00, 1.08, 1.04, 0.98,  # Jan..Aug
    0.92, 0.94, 0.97, 1.05,  # Sep..Dec (unused for Aug-only but kept)
]

# 2026 growth factors per month vs same month 2025 (-> positive YoY).
GROWTH_2026 = {
    1: 1.09, 2: 1.10, 3: 1.08, 4: 1.11, 5: 1.10,
    6: 1.12, 7: 1.105, 8: 1.107,
}

TARGET_ACHIEVEMENT = Decimal('0.945')  # revenue target ~94.5% of actual baseline
EXPENSE_RATIO = Decimal('0.801')       # expense ~80.1% of revenue
BUDGET_FACTOR = Decimal('1.067')       # budget slightly above actual expense

SHU_MARGIN_TARGET = Decimal('0.193')
OPERATING_RATIO_TARGET = Decimal('0.807')

TF_SHARE = Decimal('0.86')
NTF_PROJECT_SHARE = Decimal('0.09')
NTF_RESEARCH_SHARE = Decimal('0.05')


class Command(BaseCommand):
    help = 'Seed sample financial data (2025-2026, Jan-Aug, 4 campuses).'

    def handle(self, *args, **options):
        self.stdout.write('Seeding financial data...')
        random.seed(42)
        self._seed_masters()
        self._seed_periods_and_facts()
        self._seed_kpi_targets()
        self.stdout.write(self.style.SUCCESS('Done.'))

    def _seed_masters(self):
        Campus.objects.all().delete()
        RevenueCategory.objects.all().delete()
        OrganizationUnit.objects.all().delete()
        FinancialPeriod.objects.all().delete()
        FinancialSummary.objects.all().delete()
        RevenueTransactionSummary.objects.all().delete()
        KpiTarget.objects.all().delete()

        self.bdg = Campus.objects.create(code='BDG', name='Bandung')
        self.jkt = Campus.objects.create(code='JKT', name='Jakarta')
        self.sby = Campus.objects.create(code='SBY', name='Surabaya')
        self.pwt = Campus.objects.create(code='PWT', name='Purwokerto')
        self.campuses = [self.bdg, self.jkt, self.sby, self.pwt]

        for code, name in [('TF', 'Tuition Fee'), ('NTF_PROJECT', 'NTF Project'), ('NTF_RESEARCH', 'NTF Research Income')]:
            RevenueCategory.objects.create(code=code, name=name, category_type='REVENUE')

        self.tf = RevenueCategory.objects.get(code='TF')
        self.ntf_p = RevenueCategory.objects.get(code='NTF_PROJECT')
        self.ntf_r = RevenueCategory.objects.get(code='NTF_RESEARCH')

    def _seed_periods_and_facts(self):
        for year in (2025, 2026):
            for month in range(1, 9):
                period = FinancialPeriod.objects.create(
                    year=year,
                    month=month,
                    period_start=date(year, month, 1),
                    period_end=date(year, month, 28 if month == 2 else 30 if month in (4, 6, 9, 11) else 31),
                )
                for campus in self.campuses:
                    self._seed_month(period, campus, year, month)

    def _seed_month(self, period, campus, year, month):
        base = Decimal(BASE_REVENUE_2025[campus.code])
        weight = Decimal(str(MONTH_WEIGHTS[month - 1]))
        if year == 2025:
            revenue = base * weight
        else:
            revenue = base * weight * Decimal(str(GROWTH_2026[month]))

        revenue = revenue.quantize(Decimal('0.01'))
        expense = (revenue * EXPENSE_RATIO).quantize(Decimal('0.01'))
        budget = (expense * BUDGET_FACTOR).quantize(Decimal('0.01'))
        shu = (revenue - expense).quantize(Decimal('0.01'))
        revenue_target = (revenue / TARGET_ACHIEVEMENT).quantize(Decimal('0.01'))
        shu_target = (shu / Decimal('0.976')).quantize(Decimal('0.01'))

        FinancialSummary.objects.create(
            period=period, campus=campus, organization_unit=None,
            revenue_actual=revenue, revenue_target=revenue_target,
            expense_actual=expense, expense_budget=budget,
            shu_actual=shu, shu_target=shu_target,
        )

        # 2025 uses a different mix than 2026 so the composition YoY bars differ.
        if year == 2025:
            tf = (revenue * Decimal('0.82')).quantize(Decimal('0.01'))
            ntf_p = (revenue * Decimal('0.12')).quantize(Decimal('0.01'))
            ntf_r = (revenue * Decimal('0.06')).quantize(Decimal('0.01'))
        else:
            tf = (revenue * TF_SHARE).quantize(Decimal('0.01'))
            ntf_p = (revenue * NTF_PROJECT_SHARE).quantize(Decimal('0.01'))
            ntf_r = (revenue * NTF_RESEARCH_SHARE).quantize(Decimal('0.01'))
        # Rounding: adjust NTF Research so the three sum exactly to revenue.
        ntf_r += revenue - (tf + ntf_p + ntf_r)

        for cat, amount, target_factor in [
            (self.tf, tf, Decimal('0.951')),
            (self.ntf_p, ntf_p, Decimal('0.94')),
            (self.ntf_r, ntf_r, Decimal('0.93')),
        ]:
            RevenueTransactionSummary.objects.create(
                period=period, campus=campus, organization_unit=None,
                revenue_category=cat, actual_amount=amount,
                target_amount=(amount / target_factor).quantize(Decimal('0.01')),
            )

    def _seed_kpi_targets(self):
        for year in (2025, 2026):
            KpiTarget.objects.create(year=year, campus=None, organization_unit=None, kpi_code='OPERATING_RATIO', target_value=OPERATING_RATIO_TARGET * 100, unit='%')
            KpiTarget.objects.create(year=year, campus=None, organization_unit=None, kpi_code='SHU_MARGIN', target_value=SHU_MARGIN_TARGET * 100, unit='%')
