"""
Unit tests for all financial formulas (#64, #65).

Covers every calculation in the service layer including edge cases:
- zero denominators (no division by zero)
- YoY positive/negative/zero-previous
- Operating Ratio lower-is-better achievement
- SHU Margin higher-is-better achievement
- Revenue composition sums to ~100%
"""

from decimal import Decimal

from django.test import TestCase

from finance.services import (
    calculate_composition,
    calculate_expense_utilization,
    calculate_operating_ratio,
    calculate_operating_ratio_achievement,
    calculate_revenue_achievement,
    calculate_revenue_composition,
    calculate_shu_achievement,
    calculate_shu_margin,
    calculate_shu_margin_achievement,
    calculate_yoy_growth,
    operating_ratio_status,
    validate_revenue_composition,
)


class AchievementTests(TestCase):
    def test_revenue_achievement(self):
        self.assertEqual(calculate_revenue_achievement(94_500, 100_000), Decimal('94.50'))

    def test_revenue_achievement_zero_target(self):
        self.assertIsNone(calculate_revenue_achievement(100, 0))

    def test_expense_utilization(self):
        self.assertEqual(calculate_expense_utilization(900_800, 960_900), Decimal('93.75'))

    def test_expense_utilization_zero_budget(self):
        self.assertIsNone(calculate_expense_utilization(10, 0))

    def test_shu_achievement(self):
        self.assertEqual(calculate_shu_achievement(224_000, 229_500), Decimal('97.60'))


class YoyTests(TestCase):
    def test_yoy_positive(self):
        # (105 - 95) / 95 * 100 = 10.5263... -> 10.53
        self.assertEqual(calculate_yoy_growth(105, 95), Decimal('10.53'))

    def test_yoy_negative(self):
        self.assertEqual(calculate_yoy_growth(90, 100), Decimal('-10.00'))

    def test_yoy_zero_previous(self):
        self.assertIsNone(calculate_yoy_growth(50, 0))

    def test_yoy_none_previous(self):
        self.assertIsNone(calculate_yoy_growth(50, None))

    def test_yoy_flat(self):
        self.assertEqual(calculate_yoy_growth(100, 100), Decimal('0.00'))


class OperatingRatioTests(TestCase):
    def test_operating_ratio(self):
        # 900.8 / 1124.7 * 100 = 80.09...
        self.assertEqual(calculate_operating_ratio(1124700, 900800), Decimal('80.09'))

    def test_operating_ratio_zero_revenue(self):
        self.assertIsNone(calculate_operating_ratio(0, 900))

    def test_or_achievement_lower_is_better(self):
        # Target 80.7 / Actual 80.1 * 100 = 100.75 (lower actual -> >100%)
        self.assertEqual(calculate_operating_ratio_achievement(80.7, 80.1), Decimal('100.75'))

    def test_or_achievement_higher_actual_below_100(self):
        # Actual worse (81.5) -> achievement < 100
        self.assertEqual(calculate_operating_ratio_achievement(80.7, 81.5), Decimal('99.02'))

    def test_or_status_on_target(self):
        st = operating_ratio_status(Decimal('80.1'), Decimal('80.7'))
        self.assertEqual(st['key'], 'ON_TARGET')

    def test_or_status_watch(self):
        # actual 82.0 > target 80.7, within +2pp
        st = operating_ratio_status(Decimal('82.0'), Decimal('80.7'))
        self.assertEqual(st['key'], 'WATCH')

    def test_or_status_attention(self):
        st = operating_ratio_status(Decimal('83.5'), Decimal('80.7'))
        self.assertEqual(st['key'], 'ATTENTION')


class ShuMarginTests(TestCase):
    def test_shu_margin(self):
        # 224 / 1124.7 * 100 = 19.92
        self.assertEqual(calculate_shu_margin(224000, 1124700), Decimal('19.92'))

    def test_shu_margin_zero_revenue(self):
        self.assertIsNone(calculate_shu_margin(10, 0))

    def test_margin_achievement_higher_is_better(self):
        # Actual 19.9 / Target 19.3 * 100 = 103.11
        self.assertEqual(calculate_shu_margin_achievement(19.9, 19.3), Decimal('103.11'))

    def test_margin_achievement_below_target(self):
        self.assertEqual(calculate_shu_margin_achievement(18.5, 19.3), Decimal('95.85'))


class CompositionTests(TestCase):
    def test_composition(self):
        self.assertEqual(calculate_composition(967, 1125), Decimal('85.96'))

    def test_composition_zero_total(self):
        self.assertIsNone(calculate_composition(10, 0))

    def test_revenue_composition_sums_100(self):
        comp = calculate_revenue_composition(967_300, 101_200, 56_200)
        total_pct = (comp['TF'] or 0) + (comp['NTF_PROJECT'] or 0) + (comp['NTF_RESEARCH'] or 0)
        self.assertAlmostEqual(float(total_pct), 100.0, places=1)

    def test_validate_composition_matches_total(self):
        tf, np_, nr = Decimal('967.3'), Decimal('101.2'), Decimal('56.2')
        self.assertTrue(validate_revenue_composition(tf, np_, nr, tf + np_ + nr))

    def test_validate_composition_mismatch(self):
        self.assertFalse(validate_revenue_composition(100, 100, 100, 500))
