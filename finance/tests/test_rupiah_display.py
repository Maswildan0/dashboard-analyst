"""
Rupiah display formatting for the Revenue Ranking.

The ranking renders RKA YTD and Actual YTD per row, in the summary and in
every PP+account detail row. These tests pin the rules that keep those
columns reconcilable by eye:

  * both amounts in one row use the SAME unit (a budget and its realisation
    must never be split across M and jt),
  * two decimals are always kept — no stripping of trailing zeros, which is
    what turned Rp5,95 M into "Rp6 M",
  * the unit comes from the largest amount in the group, with sub-million
    values falling back to whole rupiah,
  * rendering never changes the number it displays.

The Variance column was removed from the UI; the underlying value is still
computed at full precision so the ranking can order by it, and that is
covered by finance.tests.test_revenue_ranking.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from dashboard.views import (
    BILLION,
    MILLION,
    _revenue_ranking,
    rupiah_amount,
    rupiah_unit,
)
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

D = Decimal


def parse_display(text):
    """Read a rendered amount back as rupiah, the way a reader would.

    Used to assert the displayed columns are arithmetically consistent.
    """
    body = text.replace('Rp', '').strip()
    negative = body.startswith('-')
    body = body.lstrip('+-').strip()
    multiplier = D('1')
    for suffix, scale in (('T', D('1e12')), ('M', BILLION), ('jt', MILLION)):
        if body.endswith(suffix):
            body = body[:-len(suffix)].strip()
            multiplier = scale
            break
    value = D(body.replace('.', '').replace(',', '.')) * multiplier
    return -value if negative else value


class RupiahUnitTests(TestCase):
    def test_unit_comes_from_the_largest_amount_in_the_group(self):
        # A Rp0,43 M shortfall must NOT drag the row down to "jt".
        unit = rupiah_unit([D('5950918800'), D('5522520000'), D('-428398800')])
        self.assertEqual(unit, ('M', BILLION))

    def test_below_a_billion_uses_juta(self):
        self.assertEqual(rupiah_unit([D('559500000'), D('-50900000')]), ('jt', MILLION))

    def test_sub_million_uses_whole_rupiah(self):
        # Trailing "0,00 jt" would misrepresent a small amount as nothing.
        self.assertEqual(rupiah_unit([D('123456')]), ('', D('1')))

    def test_boundaries(self):
        self.assertEqual(rupiah_unit([D('999000000')])[0], 'jt')
        self.assertEqual(rupiah_unit([D('1000000000')])[0], 'M')
        self.assertEqual(rupiah_unit([D('1234567890123')])[0], 'T')

    def test_empty_and_zero_are_safe(self):
        self.assertEqual(rupiah_unit([]), ('', D('1')))
        self.assertEqual(rupiah_unit([None, D('0')]), ('', D('1')))


class RupiahAmountTests(TestCase):
    def test_two_decimals_are_always_kept(self):
        """Rp5,95 M must never collapse back to "Rp6 M"."""
        unit = rupiah_unit([D('5950918800')])
        self.assertEqual(rupiah_amount(D('5950918800'), unit), 'Rp5,95 M')
        self.assertEqual(rupiah_amount(D('5522520000'), unit), 'Rp5,52 M')

    def test_indonesian_separators(self):
        # '.' separates thousands, ',' separates decimals.
        unit = ('M', BILLION)
        self.assertEqual(rupiah_amount(D('31187438148.80'), unit), 'Rp31,19 M')
        self.assertEqual(rupiah_amount(D('1234567890123'), ('T', D('1e12'))), 'Rp1,23 T')
        self.assertEqual(rupiah_amount(D('559500000'), ('jt', MILLION)), 'Rp559,50 jt')
        self.assertEqual(rupiah_amount(D('123456'), ('', D('1'))), 'Rp123.456')

    def test_negative_amounts(self):
        unit = ('M', BILLION)
        self.assertEqual(rupiah_amount(D('-1712898148.80'), unit), '-Rp1,71 M')

    def test_none_renders_as_zero(self):
        self.assertEqual(rupiah_amount(None, ('M', BILLION)), 'Rp0,00 M')


class RankingCssScopeTests(TestCase):
    """The rank badge and the rank emphasis rail share the `rr-rank-N` class.

    The badge paints its text white; the emphasis rule colours the row. An
    unscoped `.rr-rank-1 { color: #fff }` matched BOTH, so the top-three rows
    rendered their amount columns white-on-white (invisible). These tests keep
    the two rules scoped to their own element.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from pathlib import Path
        cls.css = (Path(__file__).resolve().parents[2]
                   / 'finance' / 'static' / 'finance' / 'css' / 'dashboard.css').read_text(encoding='utf-8')

    def test_rank_colour_rules_target_the_badge_only(self):
        for rank in (1, 2, 3):
            # The white-text rule must require the badge class as well.
            self.assertIn(f'.rr-rank.rr-rank-{rank} {{', self.css)
            # ...and no bare `.rr-rank-N {` rule may set a colour anywhere.
            self.assertNotRegex(
                self.css, rf'(?m)^\s*\.rr-rank-{rank}\s*\{{[^}}]*color\s*:',
                f'unscoped .rr-rank-{rank} rule sets color again')

    def test_rank_emphasis_rules_target_the_item_only(self):
        for rank in (1, 2, 3):
            self.assertIn(f'.rr-item.rr-rank-{rank} {{', self.css)


class RankingFormatConsistencyTests(TestCase):
    """Both amount columns of a row must share a unit and stay exact."""

    def setUp(self):
        period = FinancialPeriod.objects.create(
            year=2026, month=8, period_start=date(2026, 8, 1), period_end=date(2026, 8, 31),
            is_closed=False)
        campus = Campus.objects.create(code='BDG', name='Bandung')
        org = OrganizationUnit.objects.create(
            code='RI-BTP', name='DIREKTORAT BTP', campus=campus, unit_type='OTHER')
        pp = PPMaster.objects.create(pp_code='9299', organization_unit=org)
        cat = RevenueCategory.objects.create(code='TF', name='Tuition Fee')
        acc = RevenueAccount.objects.create(
            account_code='4251101', account_name='Penerimaan Hibah', revenue_category=cat)

        # The exact shape reported as broken: a Rp5,95 M budget against a
        # Rp5,52 M realisation, i.e. a Rp0,43 M shortfall.
        RevenueLedger.objects.create(
            period=period, pp=pp, revenue_account=acc,
            credit=D('5522520000'), debit=D('0'))
        version = RkaVersion.objects.create(
            year=2026, version_code='AWAL', status='ACTIVE', is_active=True)
        budget = RevenueBudget.objects.create(
            rka_version=version, year=2026, pp=pp, revenue_account=acc,
            annual_budget=D('5950918800') * 12 / 8)
        monthly = D('5950918800') / 8
        for month in range(1, 13):
            RevenueBudgetMonthly.objects.create(
                revenue_budget=budget, month=month, budget_amount=monthly)

    def _org(self):
        data = _revenue_ranking(2026)
        self.assertIsNotNone(data)
        return next(o for o in data['orgs'] if o['org'] == 'DIREKTORAT BTP')

    def test_row_renders_in_one_unit_with_two_decimals(self):
        org = self._org()
        self.assertTrue(org['rka_disp'].endswith('M'), org['rka_disp'])
        self.assertTrue(org['actual_disp'].endswith('M'), org['actual_disp'])
        self.assertRegex(org['rka_disp'], r'^Rp[\d.]+,\d{2} M$')
        self.assertRegex(org['actual_disp'], r'^Rp[\d.]+,\d{2} M$')

    def test_displayed_amounts_keep_the_raw_value(self):
        """Rendering must not change the number: re-reading the display
        reproduces the stored amount to within one last-digit step."""
        org = self._org()
        for key in ('rka', 'actual'):
            shown = parse_display(org[key + '_disp'])
            self.assertLessEqual(abs(shown - org[key]), D('0.01') * BILLION, key)
            self.assertIsInstance(org[key], Decimal)

    def test_variance_is_still_calculated_exactly(self):
        """The column is gone, but the computed variance is unchanged:
        full-precision actual - rka (other tests assert the ordering)."""
        org = self._org()
        self.assertEqual(org['variance'], org['actual'] - org['rka'])
        self.assertIsInstance(org['variance'], Decimal)
        self.assertNotEqual(org['variance'], org['variance'].quantize(D('1e6')))

    def test_detail_rows_use_the_same_shared_unit_rule(self):
        org = self._org()
        self.assertTrue(org['rows'])
        for row in org['rows']:
            units = {s.split()[-1] for s in
                     (row['rka_disp'], row['actual_disp']) if s}
            # A row never mixes 'M' with 'jt'.
            self.assertLessEqual(len(units), 1, row)


class VarianceColumnRemovedTests(RankingFormatConsistencyTests):
    """The Variance column is gone from both ranking levels.

    Reuses the ranking fixture so the payload assertions run against real
    aggregated data rather than an empty database.
    """

    def test_page_has_no_variance_column(self):
        html = self.client.get(reverse('dashboard')).content.decode()
        self.assertNotIn('>Variance<', html)

    def test_view_no_longer_builds_variance_display_strings(self):
        data = _revenue_ranking(2026)
        self.assertIsNotNone(data)
        for org in data['orgs']:
            self.assertNotIn('variance_disp', org)
            self.assertNotIn('variance_zero', org)
            self.assertTrue(org['rka_disp'] and org['actual_disp'])
            for row in org['rows']:
                self.assertNotIn('variance_disp', row)
                self.assertNotIn('variance_zero', row)
