"""
Model + selector tests (#63, #66).

The Financial Performance Overview view itself is covered by
finance.tests.test_financial_overview (service + view contract).
"""

from django.test import TestCase

from finance.models import Campus, FinancialPeriod, FinancialSummary, OrganizationUnit
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

    def test_selector_org_unit_is_scoped_to_campus(self):
        other = Campus.objects.create(code='JKT', name='Jakarta')
        unit = OrganizationUnit.objects.create(
            code='RI-JKT', name='RI JKT', campus=other, unit_type='OTHER')
        self.assertIsNone(sel.get_org_unit(str(unit.pk), self.bdg))
        self.assertEqual(sel.get_org_unit(str(unit.pk), other), unit)

    def test_selector_latest_period(self):
        self.assertEqual(sel.get_latest_period(), self.period)

    def test_selector_latest_period_of_year(self):
        FinancialPeriod.objects.create(year=2026, month=2, period_start='2026-02-01', period_end='2026-02-28')
        self.assertEqual(sel.get_latest_period_of_year(2026).month, 8)
        self.assertIsNone(sel.get_latest_period_of_year(1999))
