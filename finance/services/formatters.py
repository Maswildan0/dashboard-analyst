"""
Indonesian money & percentage formatters (#33, #34).

Defaults to "Rp Miliar" for the dashboard: 1_124_700_000_000 -> "Rp 1.124,7 M".
Uses Decimal to avoid float rounding errors.
"""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

MILLION = Decimal('1_000_000')
BILLION = Decimal('1_000_000_000')
TRILLION = Decimal('1_000_000_000_000')


def _dec(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal('0')


def format_rupiah_compact(value, decimals=1):
    """Format an amount in IDR to a compact Indonesian string.

    Defaults to "M" (Miliar). Values >= 1 trillion render as "T".
    Negative values get a leading minus. None -> 'Rp0' (empty nominal).
    """
    if value is None:
        return 'Rp0'
    v = _dec(value)
    sign = '-'
    v = abs(v)
    if v >= TRILLION:
        scaled = (v / TRILLION).quantize(Decimal(10) ** -decimals, rounding=ROUND_HALF_UP)
        unit = 'T'
    else:
        scaled = (v / BILLION).quantize(Decimal(10) ** -decimals, rounding=ROUND_HALF_UP)
        unit = 'M'
    text = f'{sign if value < 0 else ""}Rp {scaled:,} {unit}'.replace(',', '.')
    return text


def format_percent(value, decimals=1):
    """Format a percentage with the given decimals; None -> '-'."""
    if value is None:
        return '-'
    v = _dec(value)
    q = v.quantize(Decimal(10) ** -decimals, rounding=ROUND_HALF_UP)
    return f'{q:.{decimals}f}%'


def format_signed_percent(value, decimals=2):
    """Format a signed percentage (+10.53%) for YoY; None -> '-'."""
    if value is None:
        return '-'
    v = _dec(value)
    q = v.quantize(Decimal(10) ** -decimals, rounding=ROUND_HALF_UP)
    sign = '+' if v > 0 else ''
    return f'{sign}{q:.{decimals}f}%'
