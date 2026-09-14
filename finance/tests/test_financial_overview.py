"""
Financial Performance Overview: service + view integration tests.

The page has ONE canonical source per metric (finance.services.
financial_overview). These tests pin the contract that matters:

  * every figure comes from the database (GL / frozen snapshots / RKA /
    KpiTarget), never from a literal in the view,
  * the YTD card equals SUM(monthly trend Jan..selected),
  * the filters (year, month, campus, organization) really change the numbers,
  * a metric without an authoritative source renders N/A instead of a
    fabricated value.

Fixtures write the same tables the app reads, so the assertions exercise the
real query paths. Amounts are written as `n * B` (B = one billion rupiah) so
the rendered "Rp n,0 M" strings are checkable.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from finance.models import (
    Campus,
    FinancialPeriod,
    KpiTarget,
    OrganizationUnit,
    PPMaster,
    RevenueAccount,
    RevenueBudget,
    RevenueBudgetMonthly,
    RevenueCategory,
    RevenueLedger,
    RevenueMonthlySnapshot,
    RkaVersion,
)
from finance.services.financial_overview import (
    DATA_NOT_AVAILABLE,
    build_financial_overview,
)

ZERO = Decimal('0')
B = Decimal('1000000000')


class FinancialOverviewBase(TestCase):
    """2025 and 2026 Jan..Aug; Jan..Jul closed (frozen), August open (GL).

    Monthly revenue: BDG org1 = 10B, BDG org2 = 5B, JKT = 7B.
    2025 monthly:   BDG org1 =  8B, BDG org2 = 4B, JKT = 6B (-> positive YoY).
    RKA 2026: pp_bdg 24B/year (2B/month), pp_jkt 12B/year (1B/month).
    """

    def setUp(self):
        self.bdg = Campus.objects.create(code='BDG', name='Bandung')
        self.jkt = Campus.objects.create(code='JKT', name='Jakarta')
        self.org_bdg = OrganizationUnit.objects.create(
            code='RI-CCSL', name='RI-CCSL', campus=self.bdg, unit_type='OTHER')
        self.org_bdg2 = OrganizationUnit.objects.create(
            code='DITMAWA', name='DITMAWA', campus=self.bdg, unit_type='OTHER')
        self.org_jkt = OrganizationUnit.objects.create(
            code='RI-JKT', name='RI JKT', campus=self.jkt, unit_type='OTHER')
        self.pp_bdg = PPMaster.objects.create(pp_code='9114', organization_unit=self.org_bdg)
        self.pp_bdg2 = PPMaster.objects.create(pp_code='4301', organization_unit=self.org_bdg2)
        self.pp_jkt = PPMaster.objects.create(pp_code='9200', organization_unit=self.org_jkt)

        self.cat_tf = RevenueCategory.objects.create(code='TF', name='Tuition Fee')
        self.acc_tf = RevenueAccount.objects.create(
            account_code='4121135', account_name='Pddk Pelatihan', revenue_category=self.cat_tf)

        self.periods = {}
        for year in (2025, 2026):
            for month in range(1, 9):
                self.periods[(year, month)] = FinancialPeriod.objects.create(
                    year=year, month=month,
                    period_start=date(year, month, 1),
                    period_end=date(year, month, 28),
                    is_closed=(year == 2025 or month < 8),
                )

        for month in range(1, 9):
            self._revenue(2026, month, self.pp_bdg, 10)
            self._revenue(2026, month, self.pp_bdg2, 5)
            self._revenue(2026, month, self.pp_jkt, 7)
            self._revenue(2025, month, self.pp_bdg, 8)
            self._revenue(2025, month, self.pp_bdg2, 4)
            self._revenue(2025, month, self.pp_jkt, 6)

        version = RkaVersion.objects.create(
            year=2026, version_code='AWAL', status='ACTIVE', is_active=True)
        self._budget(version, self.pp_bdg, 24)
        self._budget(version, self.pp_jkt, 12)

        KpiTarget.objects.create(year=2026, kpi_code='OPERATING_RATIO', target_value='80.7')
        KpiTarget.objects.create(year=2026, kpi_code='SHU_MARGIN', target_value='19.3')

    def _revenue(self, year, month, pp, amount):
        """`amount` in billions: a closed month freezes it, an open one has GL."""
        period = self.periods[(year, month)]
        value = Decimal(amount) * B
        if period.is_closed:
            RevenueMonthlySnapshot.objects.create(
                period=period, pp=pp, revenue_account=self.acc_tf, actual_amount=value)
        else:
            RevenueLedger.objects.create(
                period=period, pp=pp, revenue_account=self.acc_tf,
                credit=value, debit=ZERO)

    def _budget(self, version, pp, annual):
        """`annual` in billions, phased evenly over 12 months."""
        budget = RevenueBudget.objects.create(
            rka_version=version, year=2026, pp=pp,
            revenue_account=self.acc_tf, annual_budget=Decimal(annual) * B)
        monthly = (Decimal(annual) * B) / Decimal('12')
        for month in range(1, 13):
            RevenueBudgetMonthly.objects.create(
                revenue_budget=budget, month=month, budget_amount=monthly)


class ServiceTests(FinancialOverviewBase):
    def test_revenue_ytd_is_january_to_selected_month(self):
        data = build_financial_overview(2026, 8)
        # BDG 15B + JKT 7B = 22B/month over Jan..Aug.
        self.assertEqual(data['revenue']['actual_ytd'], 176 * B)

    def test_revenue_is_scoped_by_campus(self):
        bdg = build_financial_overview(2026, 8, self.bdg)
        jkt = build_financial_overview(2026, 8, self.jkt)
        self.assertEqual(bdg['revenue']['actual_ytd'], 120 * B)   # 15 x 8
        self.assertEqual(jkt['revenue']['actual_ytd'], 56 * B)    # 7 x 8

    def test_revenue_is_scoped_by_organization(self):
        org1 = build_financial_overview(2026, 8, self.bdg, self.org_bdg)
        org2 = build_financial_overview(2026, 8, self.bdg, self.org_bdg2)
        self.assertEqual(org1['revenue']['actual_ytd'], 80 * B)   # 10 x 8
        self.assertEqual(org2['revenue']['actual_ytd'], 40 * B)   # 5 x 8

    def test_revenue_ytd_equals_sum_of_trend_months(self):
        """The card and the chart must reconcile (brief #32)."""
        data = build_financial_overview(2026, 8)
        self.assertEqual(sum(data['trend']['revenue'], ZERO), data['revenue']['actual_ytd'])

    def test_trend_is_monthly_actual_not_cumulative(self):
        data = build_financial_overview(2026, 8)
        self.assertEqual(data['trend']['revenue'], [22 * B] * 8)
        self.assertEqual(data['trend']['months'], list(range(1, 9)))

    def test_trend_stops_at_selected_month(self):
        data = build_financial_overview(2026, 5)
        self.assertEqual(data['trend']['months'], [1, 2, 3, 4, 5])
        self.assertEqual(data['revenue']['actual_ytd'], 110 * B)  # 22 x 5

    def test_rka_ytd_is_phased_to_the_selected_month(self):
        data = build_financial_overview(2026, 8)
        # (2B + 1B) per month over Jan..Aug.
        self.assertEqual(data['revenue']['rka_ytd'], 24 * B)

    def test_revenue_achievement_is_actual_over_rka(self):
        data = build_financial_overview(2026, 8)
        expected = (176 * B) / (24 * B) * 100
        self.assertEqual(data['revenue']['achievement'],
                         expected.quantize(Decimal('0.01')))

    def test_revenue_achievement_is_none_when_rka_is_zero(self):
        RevenueBudget.objects.all().delete()
        data = build_financial_overview(2026, 8)
        self.assertIsNone(data['revenue']['achievement'])

    def test_revenue_yoy_compares_same_ytd_window(self):
        data = build_financial_overview(2026, 8)
        # 2026 YTD 176B vs 2025 YTD (8+4+6) x 8 = 144B -> +22.22%
        self.assertEqual(data['revenue']['prev_year_ytd'], 144 * B)
        self.assertEqual(data['revenue']['yoy'], Decimal('22.22'))

    def test_expense_and_shu_are_reported_unavailable(self):
        """No authoritative expense source exists -> N/A, never a placeholder."""
        data = build_financial_overview(2026, 8)
        self.assertFalse(data['expense']['available'])
        self.assertIsNone(data['expense']['actual_ytd'])
        self.assertIsNone(data['expense']['utilization'])
        self.assertIsNone(data['shu']['actual_ytd'])
        self.assertIsNone(data['shu']['achievement'])
        self.assertIsNone(data['operating_ratio']['actual'])
        self.assertIsNone(data['shu_margin']['actual'])
        self.assertIsNone(data['trend']['expense'])
        self.assertIsNone(data['trend']['shu'])
        self.assertTrue(all(w['code'] == DATA_NOT_AVAILABLE for w in data['warnings']))

    def test_kpi_targets_come_from_the_database(self):
        data = build_financial_overview(2026, 8)
        self.assertEqual(data['operating_ratio']['target'], Decimal('80.7'))
        self.assertEqual(data['shu_margin']['target'], Decimal('19.3'))

    def test_kpi_target_is_none_when_no_row_exists(self):
        data = build_financial_overview(2025, 8)
        self.assertIsNone(data['operating_ratio']['target'])

    def test_empty_scope_returns_zero_and_no_ratio(self):
        """A filter combination without data: zero, or N/A never a fallback."""
        empty_campus = Campus.objects.create(code='PWT', name='Purwokerto')
        data = build_financial_overview(2026, 8, empty_campus)
        self.assertEqual(data['revenue']['actual_ytd'], ZERO)
        self.assertEqual(data['trend']['revenue'], [ZERO] * 8)
        self.assertIsNone(data['revenue']['yoy'])  # 0 previous -> no division


class ViewTests(FinancialOverviewBase):
    def get(self, **params):
        resp = self.client.get(reverse('finance:dashboard'), params)
        self.assertEqual(resp.status_code, 200)
        return resp

    def test_page_renders_database_revenue(self):
        html = self.get(year=2026, month=8, campus='BDG').content.decode()
        self.assertIn('Rp 120.0 M', html)

    def test_page_renders_na_for_unavailable_metrics(self):
        html = self.get(year=2026, month=8, campus='BDG').content.decode()
        # Expense/SHU cards: no source -> N/A, and never a fabricated number.
        self.assertNotIn('Rp 486', html)
        self.assertIn('N/A', html)

    def test_filters_change_the_rendered_numbers(self):
        bdg = self.get(year=2026, month=8, campus='BDG').content.decode()
        jkt = self.get(year=2026, month=8, campus='JKT').content.decode()
        self.assertIn('Rp 120.0 M', bdg)
        self.assertIn('Rp 56.0 M', jkt)

    def test_month_filter_narrows_the_ytd(self):
        aug = self.get(year=2026, month=8, campus='BDG').content.decode()
        may = self.get(year=2026, month=5, campus='BDG').content.decode()
        self.assertIn('Rp 120.0 M', aug)
        self.assertIn('Rp 75.0 M', may)  # 15 x 5

    def test_organization_filter_applies(self):
        html = self.get(
            year=2026, month=8, campus='BDG', unit=str(self.org_bdg.pk)).content.decode()
        self.assertIn('Rp 80.0 M', html)

    def test_organization_of_another_campus_is_dropped(self):
        """Cascading filter: a foreign organization must not be applied (#26)."""
        html = self.get(
            year=2026, month=8, campus='BDG', unit=str(self.org_jkt.pk)).content.decode()
        # Falls back to All Unit -> the whole BDG campus.
        self.assertIn('Rp 120.0 M', html)

    def test_period_label_follows_the_filter(self):
        html = self.get(year=2025, month=7, campus='BDG').content.decode()
        self.assertIn('Juli 2025', html)

    def test_unknown_period_renders_empty_state(self):
        html = self.get(year=2020, month=1, campus='BDG').content.decode()
        self.assertIn('No financial data available', html)

    def test_trend_payload_carries_real_monthly_series(self):
        resp = self.get(year=2026, month=8, campus='BDG')
        trend = resp.context['trend_json']
        self.assertIn('"revenue": [15.0, 15.0', trend)
        # No fabricated Expense/SHU series in the payload.
        self.assertIn('"expense": null', trend)
        self.assertIn('"shu": null', trend)

    def test_insights_are_populated_for_the_disabled_section(self):
        """The insight section is commented out but still rendered, so the
        list must exist (built from the same figures as the cards)."""
        resp = self.get(year=2026, month=8, campus='BDG')
        insights = resp.context['m']['insights']
        self.assertTrue(insights)
        # Only metrics with a source may be described: no expense/SHU claim.
        text = ' '.join(i['text'] for i in insights)
        self.assertIn('Revenue increased', text)
        self.assertNotIn('Expense growth', text)
