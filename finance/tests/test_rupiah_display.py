"""
Rupiah display formatting for the Revenue Ranking.

The ranking renders three amount columns per row (RKA / Actual / Variance,
plus the same trio in every PP+account detail row). These tests pin the rules
that keep those columns reconcilable by eye:

  * every amount in one row uses the SAME unit (so a Rp5,95 M budget and its
    Rp0,43 M shortfall are not split across M and jt),
  * two decimals are always kept — no stripping of trailing zeros, which is
    what turned Rp5,95 M into "Rp6 M",
  * the unit comes from the largest amount in the group, with sub-million
    values falling back to whole rupiah,
  * formatting never changes the numbers: variance stays actual - rka.

Formatting is presentation only; the calculations it displays are covered by
finance.tests.test_revenue_ranking.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from dashboard.views import (
    BILLION,
    MILLION,
    _revenue_ranking,
    _rounds_to_zero,
    rupiah_amount,
    rupiah_signed,
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

    def test_signed_variance(self):
        unit = ('M', BILLION)
        self.assertEqual(rupiah_signed(D('100000000'), unit), '+Rp0,10 M')
        self.assertEqual(rupiah_signed(D('-428398800'), unit), '-Rp0,43 M')

    def test_variance_rounding_to_zero_is_not_signed(self):
        """A 3-sen difference is not a gain; '+Rp0,00 M' would imply one."""
        unit = ('M', BILLION)
        self.assertEqual(rupiah_signed(D('0.03'), unit), 'Rp0,00 M')
        self.assertEqual(rupiah_signed(D('0'), unit), 'Rp0,00 M')
        self.assertTrue(_rounds_to_zero('0,00'))
        self.assertFalse(_rounds_to_zero('0,01'))

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
    """The three amount columns of a row must share a unit and reconcile."""

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
        self.assertTrue(org['variance_disp'].endswith('M'), org['variance_disp'])
        self.assertRegex(org['rka_disp'], r'^Rp[\d.]+,\d{2} M$')
        self.assertRegex(org['actual_disp'], r'^Rp[\d.]+,\d{2} M$')
        self.assertRegex(org['variance_disp'], r'^[-+]?Rp[\d.]+,\d{2} M$')

    def test_displayed_columns_reconcile(self):
        """Actual - RKA == Variance, within one last-digit rounding step."""
        org = self._org()
        drift = abs((parse_display(org['actual_disp']) - parse_display(org['rka_disp']))
                    - parse_display(org['variance_disp']))
        # One step of the last displayed digit (0,01 M) at most.
        self.assertLessEqual(drift, D('0.01') * BILLION)

    def test_variance_still_uses_full_precision_not_display_values(self):
        """The stored variance is the raw difference, never a rounded one."""
        org = self._org()
        self.assertEqual(org['variance'], org['actual'] - org['rka'])
        # Both operands are Decimals with sub-unit precision, not round numbers.
        self.assertIsInstance(org['variance'], Decimal)
        self.assertNotEqual(org['variance'], org['variance'].quantize(D('1e6')))

    def test_detail_rows_use_the_same_shared_unit_rule(self):
        org = self._org()
        self.assertTrue(org['rows'])
        for row in org['rows']:
            units = {s.split()[-1] for s in
                     (row['rka_disp'], row['actual_disp'], row['variance_disp']) if s}
            # A row never mixes 'M' with 'jt'.
            self.assertLessEqual(len(units), 1, row)
            drift = abs((parse_display(row['actual_disp']) - parse_display(row['rka_disp']))
                        - parse_display(row['variance_disp']))
            self.assertLessEqual(drift, D('0.01') * BILLION)
