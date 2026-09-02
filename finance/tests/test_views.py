"""
Model + view integration tests (#63, #66).
"""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from finance.models import Campus, FinancialPeriod, FinancialSummary, RevenueCategory, RevenueTransactionSummary
from finance.selectors import financial_selectors as sel


class ModelTests(TestCase):
    def setUp(self):
        self.bdg = Campus.objects.create(code='BDG', name='Bandung')
        self.period = FinancialPeriod.objects.create(year=2026, month=8, period_start='2026-08-01', period_end='2026-08-31')
        self.summary = FinancialSummary.objects.create(
            period=self.period, campus=self.bdg, organization_unit=None,
            revenue_actual='607521600000.00', revenue_target='642879999999.99',
            expense_actual='486624801600.00', expense_budget='519208823067.20',
            shu_actual='120896798400.00', shu_target='123869671721.31',
        )

    def test_unique_period(self):
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            FinancialPeriod.objects.create(year=2026, month=8, period_start='2026-08-01', period_end='2026-08-31')

    def test_selector_get_summary(self):
        got = sel.get_financial_summary(self.period, self.bdg)
        self.assertEqual(str(got.revenue_actual), '607521600000.00')

    def test_selector_latest_period(self):
        self.assertEqual(sel.get_latest_period(), self.period)


class ViewTests(TestCase):
    def setUp(self):
        self.bdg = Campus.objects.create(code='BDG', name='Bandung')
        p25 = FinancialPeriod.objects.create(year=2025, month=8, period_start='2025-08-01', period_end='2025-08-31')
        p26 = FinancialPeriod.objects.create(year=2026, month=8, period_start='2026-08-01', period_end='2026-08-31')
        FinancialSummary.objects.create(
            period=p25, campus=self.bdg, organization_unit=None,
            revenue_actual='548800000000.00', revenue_target='580000000000.00',
            expense_actual='439588800000.00', expense_budget='469000000000.00',
            shu_actual='109211200000.00', shu_target='112000000000.00',
        )
        FinancialSummary.objects.create(
            period=p26, campus=self.bdg, organization_unit=None,
            revenue_actual='607521600000.00', revenue_target='642879999999.99',
            expense_actual='486624801600.00', expense_budget='519208823067.20',
            shu_actual='120896798400.00', shu_target='123869671721.31',
        )
        tf = RevenueCategory.objects.create(code='TF', name='Tuition Fee')
        for p, amt, tgt in [(p26, '522468576000.00', '549388618296.53'), (p25, '471968000000.00', '496277602523.66')]:
            RevenueTransactionSummary.objects.create(period=p, campus=self.bdg, organization_unit=None, revenue_category=tf, actual_amount=amt, target_amount=tgt)

    def test_dashboard_renders(self):
        resp = self.client.get(reverse('finance:dashboard'), {'year': 2026, 'month': 8, 'campus': 'BDG'})
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        for label in ['Total Revenue', 'Total Expense', 'Total SHU', 'Operating Ratio', 'SHU Margin', 'Tuition Fee']:
            self.assertIn(label, html)

    def test_dashboard_empty_state(self):
        resp = self.client.get(reverse('finance:dashboard'), {'year': 2000, 'month': 1, 'campus': 'BDG'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('No financial data available', resp.content.decode())

    def test_yoy_same_month_previous_year(self):
        resp = self.client.get(reverse('finance:dashboard'), {'year': 2026, 'month': 8, 'campus': 'BDG'})
        ctx = resp.context
        # 607521600000 vs 548800000000 -> +10.70%
        self.assertIsNotNone(ctx['m']['revenue_yoy'])
        self.assertAlmostEqual(float(ctx['m']['revenue_yoy']), 10.70, places=1)
