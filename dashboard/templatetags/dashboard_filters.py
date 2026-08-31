"""Template filters ported from Blade helpers used by the original views."""

from django import template

register = template.Library()


@register.filter
def intcomma(value):
    """Indonesian-style thousands separator (dots), matching Blade's
    number_format($v, 0, ',', '.')."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return value
    sign = '-' if n < 0 else ''
    digits = str(abs(n))
    parts = []
    while len(digits) > 3:
        parts.insert(0, digits[-3:])
        digits = digits[:-3]
    parts.insert(0, digits)
    return sign + '.'.join(parts)


@register.filter
def fill_pct(value, total):
    """Progress-bar fill percent + tier color, matching the Blade inline PHP:
    width = min(100, round(pendapatanBerjalan / nilai * 100)); colors mirror
    the 4-tier capaian palette. Returns a dict {'width', 'color'}."""
    try:
        pct = int(round(float(value) / max(1, float(total)) * 100))
    except (TypeError, ValueError):
        pct = 0
    pct = min(100, pct)
    if pct < 50:
        color = '#FF383C'
    elif pct < 70:
        color = '#FACC15'
    elif pct < 80:
        color = '#FF8D28'
    else:
        color = '#10B981'
    return {'width': pct, 'color': color}

@register.filter
def index(value, i):
    """1-based index into a list (triwulan badge labels)."""
    try:
        return value[i - 1]
    except (TypeError, IndexError, KeyError):
        return ''

@register.simple_tag(takes_context=True)
def sort_link(context, col):
    """Render a sort-column URL from the view-provided sortUrl callable."""
    return context['sortUrl'](col)


@register.simple_tag(takes_context=True)
def page_link(context, page):
    """Render a pagination URL from the view-provided pageUrl callable."""
    return context['pageUrl'](page)
