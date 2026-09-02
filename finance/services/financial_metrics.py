"""
Financial metric service layer.

All KPI calculations live here — never in templates (#69, #77). Functions are
pure and take/return Decimals, with explicit handling of zero/None inputs so
the dashboard never divides by zero or renders infinity (#46).

Business rules:
- YoY always compares the CURRENT SELECTED MONTH vs the SAME MONTH of the
  previous year (#53) — never YTD.
- Operating Ratio achievement is LOWER_IS_BETTER (#12).
- SHU Margin achievement is HIGHER_IS_BETTER (#13).
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

ZERO = Decimal('0')
TWO_PLACES = Decimal('0.01')


def _to_decimal(value):
    """Coerce int/float/str/Decimal to Decimal safely; None -> 0."""
    if value is None:
        return ZERO
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ZERO


def safe_percent(numerator, denominator, places=2):
    """(numerator / denominator * 100) with zero-denominator -> None."""
    numerator = _to_decimal(numerator)
    denominator = _to_decimal(denominator)
    if denominator == ZERO:
        return None
    result = (numerator / denominator) * Decimal('100')
    return result.quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP)


def calculate_revenue_achievement(actual, target):
    """Actual / Target × 100. None when target is 0."""
    return safe_percent(actual, target)


def calculate_expense_utilization(actual, budget):
    """Actual / Budget × 100 (Budget Utilization, not achievement)."""
    return safe_percent(actual, budget)


def calculate_shu_achievement(actual, target):
    return safe_percent(actual, target)


def calculate_yoy_growth(current_value, previous_year_same_month_value):
    """(current - previous) / previous × 100. Returns None when previous is 0."""
    current = _to_decimal(current_value)
    previous = _to_decimal(previous_year_same_month_value)
    if previous == ZERO:
        return None
    growth = ((current - previous) / previous) * Decimal('100')
    return growth.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def calculate_operating_ratio(revenue, expense):
    """Total Expense / Total Revenue × 100. None when revenue is 0."""
    return safe_percent(expense, revenue)


def calculate_operating_ratio_achievement(target_or, actual_or):
    """LOWER_IS_BETTER: Target / Actual × 100."""
    return safe_percent(target_or, actual_or)


def calculate_shu_margin(shu, revenue):
    """Total SHU / Total Revenue × 100. None when revenue is 0."""
    return safe_percent(shu, revenue)


def calculate_shu_margin_achievement(actual_margin, target_margin):
    """HIGHER_IS_BETTER: Actual / Target × 100."""
    return safe_percent(actual_margin, target_margin)


def calculate_composition(part, total):
    """part / total × 100. None when total is 0."""
    return safe_percent(part, total)


def calculate_revenue_composition(tf, ntf_project, ntf_research):
    """Return dict of {code: pct} + total. Composition sums to ~100%."""
    total = _to_decimal(tf) + _to_decimal(ntf_project) + _to_decimal(ntf_research)
    return {
        'TF': calculate_composition(tf, total),
        'NTF_PROJECT': calculate_composition(ntf_project, total),
        'NTF_RESEARCH': calculate_composition(ntf_research, total),
        'total': total,
    }


def validate_revenue_composition(tf, ntf_project, ntf_research, total_revenue, tolerance=Decimal('0.5')):
    """Return True if TF+NTF+Research ≈ Total Revenue within rounding tolerance."""
    total = _to_decimal(tf) + _to_decimal(ntf_project) + _to_decimal(ntf_research)
    diff = abs(total - _to_decimal(total_revenue))
    return diff <= tolerance


def operating_ratio_status(actual_or, target_or):
    """Status for Operating Ratio (LOWER_IS_BETTER):
    ON TARGET if actual <= target; WATCH if within +2pp; else ATTENTION."""
    if actual_or is None or target_or is None:
        return {'key': 'NA', 'label': 'N/A', 'color': '#6B7280'}
    if actual_or <= target_or:
        return {'key': 'ON_TARGET', 'label': 'On Target', 'color': '#16A34A'}
    if actual_or <= target_or + Decimal('2.00'):
        return {'key': 'WATCH', 'label': 'Watch', 'color': '#F59E0B'}
    return {'key': 'ATTENTION', 'label': 'Attention', 'color': '#DC2626'}


def achievement_status(achievement, higher_is_better=True):
    """Color status for achievement percentages:
    >=100 green, 95-99.99 yellow, <95 red (for higher-is-better metrics)."""
    if achievement is None:
        return {'key': 'NA', 'label': 'N/A', 'color': '#6B7280'}
    if higher_is_better:
        if achievement >= Decimal('100'):
            return {'key': 'OK', 'label': 'On Target', 'color': '#16A34A'}
        if achievement >= Decimal('95'):
            return {'key': 'WATCH', 'label': 'Watch', 'color': '#F59E0B'}
        return {'key': 'LOW', 'label': 'Below Target', 'color': '#DC2626'}
    # Lower-is-better (operating ratio achievement): higher achievement is
    # better (target/actual), so same tiers apply.
    if achievement >= Decimal('100'):
        return {'key': 'OK', 'label': 'On Target', 'color': '#16A34A'}
    if achievement >= Decimal('95'):
        return {'key': 'WATCH', 'label': 'Watch', 'color': '#F59E0B'}
    return {'key': 'LOW', 'label': 'Below Target', 'color': '#DC2626'}
