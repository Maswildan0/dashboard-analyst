"""
Rule-based financial analyst insights (#21, #35).

Generates 3-5 deterministic insights from computed metrics. No AI API pure
business rules comparing the selected month vs the same month last year.
"""

from decimal import Decimal


def generate_financial_insights(metrics):
    """metrics: dict with revenue/expense/shu, their YoY, margins, composition,
    operating ratio. Returns list of {icon, text, tone}."""
    insights = []
    rev_yoy = metrics.get('revenue_yoy')
    exp_yoy = metrics.get('expense_yoy')
    shu_yoy = metrics.get('shu_yoy')
    shu_margin_achievement = metrics.get('shu_margin_achievement')
    or_status = metrics.get('or_status')
    composition = metrics.get('composition') or {}
    year = metrics.get('year')
    month = metrics.get('month')
    prev_year = (year or 0) - 1

    def yoy_label(v):
        if v is None:
            return 'N/A'
        return f'{v:+.2f}%'

    if rev_yoy is not None:
        if rev_yoy > 0:
            insights.append({
                'icon': 'trending-up',
                'tone': 'up',
                'text': f'Revenue increased {yoy_label(rev_yoy)} compared with the same month in {prev_year}.',
            })
        else:
            insights.append({
                'icon': 'trending-down',
                'tone': 'down',
                'text': f'Revenue declined {yoy_label(rev_yoy)} compared with the same month in {prev_year}.',
            })

    if exp_yoy is not None and rev_yoy is not None:
        if exp_yoy < rev_yoy:
            insights.append({
                'icon': 'check-circle',
                'tone': 'up',
                'text': f'Expense growth of {yoy_label(exp_yoy)} remained below revenue growth ({yoy_label(rev_yoy)}).',
            })
        else:
            insights.append({
                'icon': 'alert-triangle',
                'tone': 'down',
                'text': f'Expense growth of {yoy_label(exp_yoy)} outpaced revenue growth ({yoy_label(rev_yoy)}).',
            })

    if shu_margin_achievement is not None:
        if shu_margin_achievement >= Decimal('100'):
            insights.append({
                'icon': 'award',
                'tone': 'up',
                'text': f'SHU Margin exceeded its target by {(shu_margin_achievement - 100).quantize(Decimal("0.1"))} percentage points.',
            })
        else:
            insights.append({
                'icon': 'alert-triangle',
                'tone': 'down',
                'text': f'SHU Margin fell short of its target by {(100 - shu_margin_achievement).quantize(Decimal("0.1"))} percentage points.',
            })

    # Highest YoY revenue source
    source_yoy = {
        'TF': metrics.get('tf_yoy'),
        'NTF Project': metrics.get('ntf_project_yoy'),
        'NTF Research': metrics.get('ntf_research_yoy'),
    }
    valid = {k: v for k, v in source_yoy.items() if v is not None}
    if valid:
        top = max(valid, key=valid.get)
        insights.append({
            'icon': 'pie-chart',
            'tone': 'neutral',
            'text': f'{top} recorded the highest YoY growth ({yoy_label(valid[top])}) among revenue sources.',
        })

    if or_status and or_status['key'] != 'NA':
        insights.append({
            'icon': 'activity',
            'tone': 'up' if or_status['key'] == 'ON_TARGET' else 'down',
            'text': f"Operating Ratio is {or_status['label'].lower()}. {or_status['label']} is below the target ratio." if or_status['key'] == 'ON_TARGET' else f"Operating Ratio requires attention actual exceeds target by more than 2 percentage points." if or_status['key'] == 'ATTENTION' else f"Operating Ratio is under watch actual slightly exceeds target.",
        })

    return insights[:5]
