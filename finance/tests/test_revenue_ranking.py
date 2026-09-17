"""
Revenue Ranking by Organization: aggregation + presentation contract.

The ranking is a LEVEL-1 (organization) list with LEVEL-2 (PP + account)
detail. These tests pin:
  * the two aggregation levels and that each org total equals the sum of its
    own PP/account rows,
  * ordering (achievement desc, actual desc as tie-breaker),
  * the variance / achievement formulas and the zero-RKA guard,
  * the badge tiers the template colours from,
  * that a year with no data renders nothing instead of a stub.

Fixtures write the real tables (ledger / snapshot / RKA), so the queries under
test are the production ones.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from dashboard.views import _ach_tier, _revenue_ranking
from finance.models import (
    Campus,
    FinancialPeriod,
    OrganizationUnit,
    PPMaster,
    RevenueAccount,
    RevenueBudget,
    RevenueBudgetMonthly,
    RevenueCategory,
    RevenueLedger,
    RkaVersion,
)
from finance.services.financial_overview import revenue_ranking

B = Decimal('1000000000')
ZERO = Decimal('0')


class RankingBase(TestCase):
    """Two organizations with deliberately different achievement ratios.

    ORG_HIGH : RKA 10B, actual 9B  -> 90.0%
    ORG_LOW  : RKA 10B, actual 5B  -> 50.0%
    ORG_HIGH has two accounts so the level-2 grouping is exercised.
    """

    def setUp(self):
        # Private application: the page test below needs a signed-in analyst.
        self.client.force_login(User.objects.create_user('analyst', password='x'))
        self.period = FinancialPeriod.objects.create(
            year=2026, month=8, period_start=date(2026, 8, 1), period_end=date(2026, 8, 31),
            is_closed=False)

        campus = Campus.objects.create(code='BDG', name='Bandung')
        self.org_high = OrganizationUnit.objects.create(
            code='RI-HIGH', name='ORG HIGH', campus=campus, unit_type='OTHER')
        self.org_low = OrganizationUnit.objects.create(
            code='RI-LOW', name='ORG LOW', campus=campus, unit_type='OTHER')

        self.pp_high_a = PPMaster.objects.create(pp_code='9001', organization_unit=self.org_high)
        self.pp_high_b = PPMaster.objects.create(pp_code='9002', organization_unit=self.org_high)
        self.pp_low = PPMaster.objects.create(pp_code='9003', organization_unit=self.org_low)

        cat = RevenueCategory.objects.create(code='TF', name='Tuition Fee')
        self.acc_a = RevenueAccount.objects.create(
            account_code='4110101', account_name='Pendapatan Pendidikan', revenue_category=cat)
        self.acc_b = RevenueAccount.objects.create(
            account_code='4140101', account_name='Pendapatan Kerja Sama Proyek', revenue_category=cat)

        # --- actual (open period -> live ledger) ---
        self._gl(self.pp_high_a, self.acc_a, 6 * B)   # achieves 120% against 5B
        self._gl(self.pp_high_b, self.acc_b, 3 * B)   # achieves 60% against 5B
        self._gl(self.pp_low, self.acc_a, 5 * B)      # achieves 50% against 10B

        # --- RKA (active version, phased monthly) ---
        version = RkaVersion.objects.create(
            year=2026, version_code='AWAL', status='ACTIVE', is_active=True)
        self._budget(version, self.pp_high_a, self.acc_a, 5 * B)
        self._budget(version, self.pp_high_b, self.acc_b, 5 * B)
        self._budget(version, self.pp_low, self.acc_a, 10 * B)

    def _gl(self, pp, account, amount):
        RevenueLedger.objects.create(
            period=self.period, pp=pp, revenue_account=account, credit=amount, debit=ZERO)

    def _budget(self, version, pp, account, annual):
        budget = RevenueBudget.objects.create(
            rka_version=version, year=2026, pp=pp, revenue_account=account,
            annual_budget=annual)
        monthly = annual / Decimal('12')
        for month in range(1, 13):
            RevenueBudgetMonthly.objects.create(
                revenue_budget=budget, month=month, budget_amount=monthly)


class RankingAggregationTests(RankingBase):
    def test_org_total_equals_sum_of_its_own_rows(self):
        data = revenue_ranking(2026, 8)
        self.assertTrue(data['orgs'])
        for org in data['orgs']:
            self.assertEqual(org['actual'], sum((r['actual'] for r in org['rows']), ZERO))
            self.assertEqual(org['rka'], sum((r['rka'] for r in org['rows']), ZERO))

    def test_org_level_aggregation_and_counts(self):
        data = revenue_ranking(2026, 8)
        by_org = {o['org']: o for o in data['orgs']}
        high = by_org['ORG HIGH']
        # 6B + 3B actual; RKA is the sum of the 8 phased months.
        self.assertEqual(high['actual'], 9 * B)
        self.assertAlmostEqual(
            float(high['rka']), float((10 * B) * 8 / 12), delta=1.0)
        self.assertEqual(high['pp_count'], 2)
        self.assertEqual(high['account_count'], 2)

    def test_detail_grain_is_pp_plus_account(self):
        data = revenue_ranking(2026, 8)
        high = next(o for o in data['orgs'] if o['org'] == 'ORG HIGH')
        keys = {(r['pp_code'], r['account_code']) for r in high['rows']}
        self.assertEqual(keys, {('9001', '4110101'), ('9002', '4140101')})
        # Account names resolve from the master, not from the code.
        names = {r['account_name'] for r in high['rows']}
        self.assertIn('Pendapatan Pendidikan', names)

    def test_variance_and_achievement_formulas(self):
        data = revenue_ranking(2026, 8)
        for org in data['orgs']:
            self.assertEqual(org['variance'], org['actual'] - org['rka'])
            if org['rka'] > ZERO:
                self.assertEqual(org['achievement'], org['actual'] / org['rka'] * 100)
            else:
                self.assertIsNone(org['achievement'])
            for row in org['rows']:
                self.assertEqual(row['variance'], row['actual'] - row['rka'])
                if row['rka'] > ZERO:
                    self.assertEqual(row['achievement'], row['actual'] / row['rka'] * 100)

    def test_zero_rka_yields_none_not_division_error(self):
        RevenueBudget.objects.all().delete()
        RevenueBudgetMonthly.objects.all().delete()
        data = revenue_ranking(2026, 8)
        self.assertTrue(data['orgs'])
        for org in data['orgs']:
            self.assertIsNone(org['achievement'])

    def test_totals_reconcile_with_source_tables(self):
        from django.db.models import Sum
        data = revenue_ranking(2026, 8)
        gl = RevenueLedger.objects.filter(period=self.period).aggregate(
            c=Sum('credit'), d=Sum('debit'))
        self.assertEqual(
            sum((o['actual'] for o in data['orgs']), ZERO),
            (gl['c'] or ZERO) - (gl['d'] or ZERO))
        phased = RevenueBudgetMonthly.objects.filter(
            revenue_budget__rka_version__is_active=True, month__lte=8
        ).aggregate(s=Sum('budget_amount'))['s'] or ZERO
        # Same source, summed differently (row-by-row Decimal vs the backend's
        # aggregate), so compare within a sub-rupiah tolerance.
        self.assertAlmostEqual(
            float(sum((o['rka'] for o in data['orgs']), ZERO)), float(phased), delta=1.0)

    def test_orgs_sorted_by_achievement_then_actual(self):
        data = revenue_ranking(2026, 8)
        keys = [(o['achievement'] is None, -(o['achievement'] or ZERO), -o['actual'])
                for o in data['orgs']]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(data['orgs'][0]['org'], 'ORG HIGH')  # 90% beats 50%

    def test_detail_rows_sorted_by_achievement_within_org(self):
        data = revenue_ranking(2026, 8)
        for org in data['orgs']:
            keys = [(r['achievement'] is None, -(r['achievement'] or ZERO), -r['actual'])
                    for r in org['rows']]
            self.assertEqual(keys, sorted(keys))
        high = next(o for o in data['orgs'] if o['org'] == 'ORG HIGH')
        # 9001 achieves 120%, 9002 only 60% -> highest first.
        self.assertEqual(high['rows'][0]['pp_code'], '9001')

    def test_ranks_are_sequential_from_one(self):
        data = revenue_ranking(2026, 8)
        self.assertEqual([o['rank'] for o in data['orgs']], list(range(1, len(data['orgs']) + 1)))
        for org in data['orgs']:
            self.assertEqual([r['rank'] for r in org['rows']], list(range(1, len(org['rows']) + 1)))

    def test_summary_counts_and_top_performer(self):
        data = revenue_ranking(2026, 8)
        self.assertEqual(data['org_count'], len(data['orgs']))
        self.assertEqual(data['account_count'], sum(len(o['rows']) for o in data['orgs']))
        self.assertEqual(data['top'], data['orgs'][0]['org'])


class RankingTierTests(TestCase):
    def test_badge_tiers(self):
        self.assertEqual(_ach_tier(Decimal('120')), 'high')   # >= 100
        self.assertEqual(_ach_tier(Decimal('100')), 'high')
        self.assertEqual(_ach_tier(Decimal('99.99')), 'mid')  # 90-99.99
        self.assertEqual(_ach_tier(Decimal('90')), 'mid')
        self.assertEqual(_ach_tier(Decimal('89.99')), 'low')  # < 90
        self.assertEqual(_ach_tier(None), 'na')


class RankingViewTests(RankingBase):
    def test_view_exposes_display_strings(self):
        data = _revenue_ranking(2026)
        self.assertIsNotNone(data)
        for org in data['orgs']:
            self.assertTrue(org['rka_disp'].startswith('Rp') or org['rka_disp'] == 'Rp0')
            self.assertIn(org['ach_tier'], ('high', 'mid', 'low', 'na'))
            self.assertIsInstance(org['ach_width'], int)
            # Progress width is capped so an over-achiever cannot overflow.
            self.assertLessEqual(org['ach_width'], 120)
            for row in org['rows']:
                self.assertIn(row['ach_tier'], ('high', 'mid', 'low', 'na'))

    def test_view_is_none_for_a_year_without_data(self):
        self.assertIsNone(_revenue_ranking(1999))

    def test_page_renders_the_ranking_section(self):
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('Revenue Ranking by Organization', html)
        self.assertIn('Urutan organisasi berdasarkan achievement revenue tertinggi', html)
        # The flat table it replaced must be gone.
        self.assertNotIn('Revenue Performance by Organization / PP', html)
        # Both levels are present.
        self.assertIn('data-rr-item', html)
        self.assertIn('Detail PP &amp; Akun', html)
        self.assertIn('rr-sort-btn', html)
        self.assertIn('id="rr-search"', html)

    def test_ranking_row_is_a_clickable_button(self):
        html = self.client.get(reverse('dashboard')).content.decode()
        self.assertIn('data-rr-toggle', html)
        self.assertIn('aria-expanded="false"', html)
