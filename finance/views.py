"""
Dashboard view: builds the full financial performance overview context.

Fetches base data via selectors (aggregated queries), computes all KPIs in
the service layer, formats for display, and assembles insight texts. No
business math in templates (#70).
"""

from decimal import Decimal

from django.shortcuts import render

from dashboard.views import _assets_head, _fonts_head

from .selectors import financial_selectors as sel
from .services import (
    calculate_composition,
    calculate_revenue_composition,
    calculate_expense_utilization,
    calculate_operating_ratio,
    calculate_operating_ratio_achievement,
    calculate_revenue_achievement,
    calculate_shu_achievement,
    calculate_shu_margin,
    calculate_shu_margin_achievement,
    calculate_yoy_growth,
    format_percent,
    format_rupiah_compact,
    format_signed_percent,
    generate_financial_insights,
    operating_ratio_status,
    validate_revenue_composition,
)

MONTH_NAMES = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember']


def _default_filters(request):
    """Resolve period/campus/unit from GET, falling back to latest period."""
    latest = sel.get_latest_period()
    has_filter = 'year' in request.GET or 'month' in request.GET
    if has_filter:
        try:
            year = int(request.GET.get('year'))
            month = int(request.GET.get('month'))
        except (TypeError, ValueError):
            year = latest.year if latest else 2026
            month = latest.month if latest else 8
        period = sel.get_period(year, month)
    else:
        year = latest.year if latest else 2026
        month = latest.month if latest else 8
        period = latest

    campus_code = request.GET.get('campus') or 'all'
    campus = sel.get_campus(campus_code)
    # Default to the first campus when "All Campus" is selected so the
    # landing page has real data to show (#5).
    if campus is None:
        campuses = sel.list_campuses()
        if campuses:
            campus = campuses[0]
        else:
            campus = None
    unit = request.GET.get('unit') or 'all'
    org_unit = None
    if unit != 'all':
        org_unit = sel.list_org_units(campus).__class__ and None  # resolved below
    # resolve org unit by id
    from finance.models import OrganizationUnit
    if unit not in ('all', '') and unit.isdigit():
        org_unit = OrganizationUnit.objects.filter(id=int(unit)).first()

    return {
        'year': year,
        'month': month,
        'period': period,
        'campus': campus,
        'campus_code': campus_code,
        'org_unit': org_unit,
        'unit': unit,
    }


def _build_metrics(filters):
    period = filters['period']
    campus = filters['campus']
    org_unit = filters['org_unit']
    if period is None or campus is None:
        return None

    prev_period = sel.get_previous_year_period(period)
    summary = sel.get_financial_summary(period, campus, org_unit)
    prev_summary = sel.get_previous_summary(prev_period, campus, org_unit)
    rev_rows = sel.get_revenue_by_category(period, campus, org_unit)
    prev_rev_rows = sel.get_previous_revenue_by_category(prev_period, campus, org_unit)

    rev = summary.revenue_actual if summary else Decimal('0')
    exp = summary.expense_actual if summary else Decimal('0')
    shu = summary.shu_actual if summary else Decimal('0')
    rev_target = summary.revenue_target if summary else Decimal('0')
    exp_budget = summary.expense_budget if summary else Decimal('0')
    shu_target = summary.shu_target if summary else Decimal('0')

    prev_rev = prev_summary.revenue_actual if prev_summary else None
    prev_exp = prev_summary.expense_actual if prev_summary else None
    prev_shu = prev_summary.shu_actual if prev_summary else None

    tf = rev_rows.get('TF', {}).get('actual', Decimal('0'))
    ntf_p = rev_rows.get('NTF_PROJECT', {}).get('actual', Decimal('0'))
    ntf_r = rev_rows.get('NTF_RESEARCH', {}).get('actual', Decimal('0'))
    tf_target = rev_rows.get('TF', {}).get('target', Decimal('0'))
    ntf_p_target = rev_rows.get('NTF_PROJECT', {}).get('target', Decimal('0'))
    ntf_r_target = rev_rows.get('NTF_RESEARCH', {}).get('target', Decimal('0'))
    prev_tf = prev_rev_rows.get('TF', {}).get('actual')
    prev_ntf_p = prev_rev_rows.get('NTF_PROJECT', {}).get('actual')
    prev_ntf_r = prev_rev_rows.get('NTF_RESEARCH', {}).get('actual')

    or_actual = calculate_operating_ratio(rev, exp)
    or_target = sel.get_kpi_target(period.year, 'OPERATING_RATIO', campus)
    or_achievement = calculate_operating_ratio_achievement(or_target, or_actual) if or_target is not None else None

    margin_actual = calculate_shu_margin(shu, rev)
    margin_target = sel.get_kpi_target(period.year, 'SHU_MARGIN', campus)
    margin_achievement = calculate_shu_margin_achievement(margin_actual, margin_target) if margin_target is not None else None

    composition = calculate_revenue_composition(tf, ntf_p, ntf_r)
    composition_ok = validate_revenue_composition(tf, ntf_p, ntf_r, rev)

    metrics = {
        'year': period.year,
        'month': period.month,
        'month_name': MONTH_NAMES[period.month - 1],
        'summary': summary,
        'revenue': rev, 'expense': exp, 'shu': shu,
        'revenue_target': rev_target, 'expense_budget': exp_budget, 'shu_target': shu_target,
        'revenue_achievement': calculate_revenue_achievement(rev, rev_target),
        'expense_utilization': calculate_expense_utilization(exp, exp_budget),
        'shu_achievement': calculate_shu_achievement(shu, shu_target),
        'revenue_yoy': calculate_yoy_growth(rev, prev_rev),
        'expense_yoy': calculate_yoy_growth(exp, prev_exp),
        'shu_yoy': calculate_yoy_growth(shu, prev_shu),
        'or_actual': or_actual,
        'or_target': or_target,
        'or_achievement': or_achievement,
        'margin_actual': margin_actual,
        'margin_target': margin_target,
        'margin_achievement': margin_achievement,
        'tf': tf, 'ntf_project': ntf_p, 'ntf_research': ntf_r,
        'tf_target': tf_target, 'ntf_project_target': ntf_p_target, 'ntf_research_target': ntf_r_target,
        'tf_achievement': calculate_revenue_achievement(tf, tf_target) if tf_target else None,
        'ntf_project_achievement': calculate_revenue_achievement(ntf_p, ntf_p_target) if ntf_p_target else None,
        'ntf_research_achievement': calculate_revenue_achievement(ntf_r, ntf_r_target) if ntf_r_target else None,
        'tf_yoy': calculate_yoy_growth(tf, prev_tf),
        'ntf_project_yoy': calculate_yoy_growth(ntf_p, prev_ntf_p),
        'ntf_research_yoy': calculate_yoy_growth(ntf_r, prev_ntf_r),
        'composition': composition,
        'composition_ok': composition_ok,
    }
    metrics['or_status'] = operating_ratio_status(or_actual, or_target)
    metrics['margin_status'] = _margin_status(margin_actual, margin_target)
    metrics['insights'] = generate_financial_insights(metrics)

    # Display helpers (status classes / progress widths).
    from .services import achievement_status as _astat
    metrics['revenue_status'] = _astat(metrics['revenue_achievement'])
    metrics['expense_status'] = _astat(metrics['expense_utilization'])
    metrics['shu_status'] = _astat(metrics['shu_achievement'])
    metrics['revenue_yoy_class'] = 'pos' if (metrics['revenue_yoy'] or 0) >= 0 else 'neg'
    metrics['expense_yoy_class'] = 'neg' if (metrics['expense_yoy'] or 0) > 0 else 'pos'
    metrics['shu_yoy_class'] = 'pos' if (metrics['shu_yoy'] or 0) >= 0 else 'neg'
    # progress width: cap achievement/utilization display at 120%.
    metrics['progress_width'] = _cap_pct(metrics['revenue_achievement'])
    metrics['progress_class'] = metrics['revenue_status']['key'].lower()
    metrics['expense_progress_width'] = _cap_pct(metrics['expense_utilization'])
    metrics['expense_progress_class'] = metrics['expense_status']['key'].lower()
    # Pre-formatted display strings (templates render these, no function calls).
    metrics['disp'] = _display_strings(metrics)
    return metrics


def _display_strings(m):
    f = format_rupiah_compact
    p = format_percent
    sgn = format_signed_percent
    comp = m['composition']
    return {
        'revenue': f(m['revenue']),
        'expense': f(m['expense']),
        'shu': f(m['shu']),
        'revenue_achievement': p(m['revenue_achievement']),
        'expense_utilization': p(m['expense_utilization']),
        'shu_achievement': p(m['shu_achievement']),
        'revenue_yoy': sgn(m['revenue_yoy']),
        'expense_yoy': sgn(m['expense_yoy']),
        'shu_yoy': sgn(m['shu_yoy']),
        'or_actual': p(m['or_actual']),
        'or_target': p(m['or_target']),
        'or_achievement': p(m['or_achievement']),
        'margin_actual': p(m['margin_actual']),
        'margin_target': p(m['margin_target']),
        'margin_achievement': p(m['margin_achievement']),
        'tf': f(m['tf']),
        'ntf_project': f(m['ntf_project']),
        'ntf_research': f(m['ntf_research']),
        'tf_achievement': p(m['tf_achievement']),
        'ntf_project_achievement': p(m['ntf_project_achievement']),
        'ntf_research_achievement': p(m['ntf_research_achievement']),
        'tf_yoy': sgn(m['tf_yoy']),
        'ntf_project_yoy': sgn(m['ntf_project_yoy']),
        'ntf_research_yoy': sgn(m['ntf_research_yoy']),
        'comp_tf': p(comp['TF']),
        'comp_ntfp': p(comp['NTF_PROJECT']),
        'comp_ntfr': p(comp['NTF_RESEARCH']),
        'comp_tf_raw': comp['TF'],
        'comp_ntfp_raw': comp['NTF_PROJECT'],
        'comp_ntfr_raw': comp['NTF_RESEARCH'],
    }


def _margin_status(actual_margin, target_margin):
    from .services import calculate_shu_margin_achievement
    if actual_margin is None or target_margin is None:
        return {'key': 'NA', 'label': 'N/A', 'color': '#6B7280'}
    ach = calculate_shu_margin_achievement(actual_margin, target_margin)
    from .services import achievement_status as _astat
    return _astat(ach)


def _cap_pct(value):
    if value is None:
        return 0
    return min(float(value), 120.0)


def financial_dashboard(request):
    filters = _default_filters(request)
    metrics = _build_metrics(filters)
    if metrics is None:
        # Empty state (#45): no data available for selection.
        return render(request, 'finance/dashboard.html', {
            'filters': filters,
            'empty': True,
            'active_tab': 'overview',
            'assets_head': _assets_head(),
            'fonts_head': _fonts_head(),
            'campuses': sel.list_campuses(),
            'units': sel.list_org_units(filters['campus']),
            'months': MONTH_NAMES,
            'years': [2025, 2026],
        })

    ctx = {
        'filters': filters,
        'empty': False,
        'active_tab': 'overview',
        'assets_head': _assets_head(),
        'fonts_head': _fonts_head(),
        'campuses': sel.list_campuses(),
        'units': sel.list_org_units(filters['campus']),
        'months': MONTH_NAMES,
        'years': [2025, 2026],
        'm': metrics,
        'fmt': {
            'rupiah': format_rupiah_compact,
            'pct': format_percent,
            'signed': format_signed_percent,
        },
        'trend': _trend_for(filters),
    }
    ctx['trend_json'] = __import__('json').dumps(ctx['trend'])
    return render(request, 'finance/dashboard.html', ctx)


def _trend_for(filters):
    """Monthly Revenue/Expense/SHU series for the selected year (#20)."""
    campus = filters['campus']
    org_unit = filters['org_unit']
    if campus is None:
        campus = sel.list_campuses()[0]
    rows = sel.get_trend(filters['year'], campus, org_unit)
    return {
        'months': ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'],
        'revenue': [float(r['revenue'] / 1_000_000_000) for r in rows],   # -> Rp Miliar
        'expense': [float(r['expense'] / 1_000_000_000) for r in rows],
        'shu': [float(r['shu'] / 1_000_000_000) for r in rows],
    }
