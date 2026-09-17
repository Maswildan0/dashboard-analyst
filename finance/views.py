"""
Dashboard view: Financial Performance Overview.

Every figure on the page comes from the canonical service
(finance.services.financial_overview), which reads the database (GL /
frozen revenue snapshots + RKA + KPI targets). This layer only resolves the
filters, translates the service payload into the template/card display shape,
and serializes the monthly trend series for the chart. No business math and
no data literals live here (brief #31, #32, #41).
"""

import json

from django.shortcuts import render

from dashboard.views import _assets_head, _fonts_head

from .selectors import financial_selectors as sel
from .services import achievement_status, generate_financial_insights, operating_ratio_status
from .services.financial_overview import (
    MONTH_NAMES,
    build_financial_overview,
    display_amount,
    display_percent,
    display_signed,
)

# The chart plots Rp Miliar (see finance/static/finance/js/dashboard.js).
BILLION = 1_000_000_000


def _int_param(request, key):
    try:
        return int(request.GET.get(key))
    except (TypeError, ValueError):
        return None


def _default_filters(request):
    """Resolve period/campus/organization from GET against the master data."""
    latest = sel.get_latest_period()
    if latest is None:
        # No period on file at all: the page renders its empty state, which is
        # the same filter shape with no period attached. There is nothing to
        # default the year/month from, so both stay None.
        return _resolve_scope(request, None, None, None)

    # An explicitly requested year/month is honoured literally: when no
    # FinancialPeriod matches, the page reports "no data" instead of silently
    # showing a different period's numbers (brief #34, #38).
    requested_year = _int_param(request, 'year')
    requested_month = _int_param(request, 'month')
    if requested_year is not None:
        year = requested_year
        if requested_month is not None:
            month = requested_month
        else:
            # Year only: use that year's latest month, or January when the
            # year is not on file at all (-> empty state).
            latest_of_year = sel.get_latest_period_of_year(year)
            month = latest_of_year.month if latest_of_year else 1
    else:
        year, month = latest.year, requested_month or latest.month

    period = sel.get_period(year, month)
    return _resolve_scope(request, period, year, month)


def _resolve_scope(request, period, year, month):
    """Filter dict shared by the populated and the empty-state render."""

    campus_code = request.GET.get('campus') or 'all'
    campus = sel.get_campus(campus_code)

    unit_code = request.GET.get('unit') or 'all'
    # Cascade (brief #26): an organization that is not a member of the
    # selected campus must not survive, otherwise the page would silently
    # report data from another campus.
    organization = sel.get_org_unit(unit_code, campus)
    if organization is None:
        unit_code = 'all'

    return {
        'year': year,
        'month': month,
        'period': period,
        'campus_code': campus_code,
        'campus': campus,
        'unit': unit_code,
        'organization': organization,
    }


def _cap_pct(value):
    if value is None:
        return 0
    return min(float(value), 120.0)


def _status(value):
    return achievement_status(value) if value is not None else {'key': 'NA', 'label': 'N/A', 'color': '#6B7280'}


def _metrics(overview):
    """Template display shape built strictly from the service payload."""
    revenue = overview['revenue']
    expense = overview['expense']
    shu = overview['shu']
    or_ = overview['operating_ratio']
    margin = overview['shu_margin']

    revenue_status = _status(revenue['achievement'])
    expense_status = _status(expense['utilization'])
    shu_status = _status(shu['achievement'])

    m = {
        'year': overview['period']['year'],
        'month': overview['period']['month'],
        'month_name': overview['period']['month_name'],
        'period': overview,
        'revenue': revenue['actual_ytd'],
        'expense': expense['actual_ytd'],
        'shu': shu['actual_ytd'],
        'revenue_target': revenue['rka_ytd'],
        'expense_budget': expense['budget_ytd'],
        'shu_target': shu['target_ytd'],
        'revenue_achievement': revenue['achievement'],
        'expense_utilization': expense['utilization'],
        'shu_achievement': shu['achievement'],
        'revenue_yoy': revenue['yoy'],
        'expense_yoy': expense['yoy'],
        'shu_yoy': shu['yoy'],
        'or_actual': or_['actual'],
        'or_target': or_['target'],
        'or_achievement': or_['achievement'],
        'margin_actual': margin['actual'],
        'margin_target': margin['target'],
        'margin_achievement': margin['achievement'],
        'revenue_status': revenue_status,
        'expense_status': expense_status,
        'shu_status': shu_status,
        'or_status': operating_ratio_status(or_['actual'], or_['target']),
        'margin_status': _status(margin['achievement']),
        'revenue_available': revenue['available'],
        'expense_available': expense['available'],
        'shu_available': shu['available'],
        'warnings': overview['warnings'],
    }
    # The insight section is commented out in dashboard.html but its
    # {% include %} still executes, so keep the list populated.
    m['insights'] = generate_financial_insights(m)

    # YoY colour: revenue/SHU rising is good, expense rising is not.
    m['revenue_yoy_class'] = 'neg' if (revenue['yoy'] is not None and revenue['yoy'] < 0) else 'pos'
    m['expense_yoy_class'] = 'neg' if (expense['yoy'] is not None and expense['yoy'] > 0) else 'pos'
    m['shu_yoy_class'] = 'neg' if (shu['yoy'] is not None and shu['yoy'] < 0) else 'pos'

    # Progress bars: achievement/utilization capped at 120% for display.
    m['progress_width'] = _cap_pct(revenue['achievement'])
    m['progress_class'] = revenue_status['key'].lower()
    m['expense_progress_width'] = _cap_pct(expense['utilization'])
    m['expense_progress_class'] = expense_status['key'].lower()
    m['shu_progress_width'] = _cap_pct(shu['achievement'])
    m['shu_progress_class'] = shu_status['key'].lower()

    m['disp'] = {
        'revenue': display_amount(revenue['actual_ytd']),
        'expense': display_amount(expense['actual_ytd']),
        'shu': display_amount(shu['actual_ytd']),
        'revenue_target': display_amount(revenue['rka_ytd']),
        'expense_budget': display_amount(expense['budget_ytd']),
        'shu_target': display_amount(shu['target_ytd']),
        'revenue_achievement': display_percent(revenue['achievement']),
        'expense_utilization': display_percent(expense['utilization']),
        'shu_achievement': display_percent(shu['achievement']),
        'revenue_yoy': display_signed(revenue['yoy']),
        'expense_yoy': display_signed(expense['yoy']),
        'shu_yoy': display_signed(shu['yoy']),
        'or_actual': display_percent(or_['actual']),
        'or_target': display_percent(or_['target']),
        'or_achievement': display_percent(or_['achievement']),
        'margin_actual': display_percent(margin['actual']),
        'margin_target': display_percent(margin['target']),
        'margin_achievement': display_percent(margin['achievement']),
    }
    return m


def _trend_json(overview):
    """Monthly ACTUAL series (not cumulative) for the chart, in Rp Miliar."""
    trend = overview['trend']

    def to_billions(values):
        if values is None:
            return None
        return [float(v / BILLION) for v in values]

    return json.dumps({
        'months': trend['labels'],
        'revenue': to_billions(trend['revenue']),
        'expense': to_billions(trend['expense']),
        'shu': to_billions(trend['shu']),
    })


def financial_dashboard(request):
    filters = _default_filters(request)
    period = filters['period']

    context = {
        'filters': filters,
        'active_tab': 'overview',
        'assets_head': _assets_head(),
        'fonts_head': _fonts_head(),
        'campuses': sel.list_campuses(),
        # Every active organization is rendered with its campus so the client
        # can cascade the list when Campus changes; the submitted value is
        # validated server-side (see _default_filters).
        'units': sel.list_org_units(),
        'months': MONTH_NAMES,
        'years': sel.list_years(),
    }

    if period is None:
        # No period on file for the selection: real empty state (brief #38).
        context['empty'] = True
        return render(request, 'finance/dashboard.html', context)

    overview = build_financial_overview(
        period.year, period.month, filters['campus'], filters['organization'])
    context.update({
        'empty': False,
        'm': _metrics(overview),
        'trend_json': _trend_json(overview),
    })
    return render(request, 'finance/dashboard.html', context)
