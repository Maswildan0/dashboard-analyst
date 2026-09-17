"""Services package exports.

`finance.services.financial_overview` is the canonical Financial Performance
Overview source; the rest are shared KPI formulas, formatters and the
revenue-module services.
"""
from .financial_metrics import (
    achievement_status,
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
from .formatters import format_percent, format_rupiah_compact, format_signed_percent
from .insights import generate_financial_insights
from .financial_overview import (
    DATA_NOT_AVAILABLE,
    MONTH_ABBR,
    MONTH_NAMES,
    build_financial_overview,
    display_amount,
    display_percent,
    display_signed,
    kpi_target,
    revenue_by_category_ytd,
    revenue_by_month,
    revenue_ranking,
    rka_by_month,
    rka_ytd,
)

__all__ = [
    'achievement_status',
    'calculate_revenue_achievement',
    'calculate_expense_utilization',
    'calculate_shu_achievement',
    'calculate_yoy_growth',
    'calculate_operating_ratio',
    'calculate_operating_ratio_achievement',
    'calculate_shu_margin',
    'calculate_shu_margin_achievement',
    'calculate_composition',
    'calculate_revenue_composition',
    'validate_revenue_composition',
    'operating_ratio_status',
    'format_rupiah_compact',
    'format_percent',
    'format_signed_percent',
    'generate_financial_insights',
    # --- Financial Performance Overview (canonical) ---
    'DATA_NOT_AVAILABLE',
    'MONTH_ABBR',
    'MONTH_NAMES',
    'build_financial_overview',
    'display_amount',
    'display_percent',
    'display_signed',
    'kpi_target',
    'revenue_by_category_ytd',
    'revenue_by_month',
    'revenue_ranking',
    'rka_by_month',
    'rka_ytd',
]

# --- Revenue module services ---
from .revenue_service import (
    actual_amount,
    actual_ytd,
    composition,
    monthly_series,
    org_pp_performance,
    yoy_series,
)
from .revenue_budget_service import (
    annual_sum,
    compare_actual_vs_rka,
    monthly_sum,
    validate_phasing,
)
from .account_classification import classify_account, normalize_description

__all__ += [
    'actual_amount',
    'actual_ytd',
    'composition',
    'monthly_series',
    'org_pp_performance',
    'yoy_series',
    'annual_sum',
    'compare_actual_vs_rka',
    'monthly_sum',
    'validate_phasing',
    'classify_account',
    'normalize_description',
]
from .revenue_project_service import (
    account_category_rows,
    account_gl_history,
    tf_account_pp_rows,
    tf_program_rows,
    research_object_rows,
    service_object_rows,
    account_month_gl,
    tf_account_pp_gl,
    gl_grain_rows,
    project_account_label,
    project_account_mode,
    project_lifetime,
    project_month,
    project_rows,
    project_status,
    project_summary,
    project_ytd,
    recognition_history,
)
__all__ += [
    'account_category_rows', 'account_gl_history', 'account_month_gl',
    'gl_grain_rows', 'tf_account_pp_gl', 'tf_account_pp_rows', 'tf_program_rows',
    'research_object_rows', 'service_object_rows',
    'project_account_label', 'project_account_mode', 'project_lifetime', 'project_month', 'project_rows',
    'project_status', 'project_summary', 'project_ytd', 'recognition_history',
]
