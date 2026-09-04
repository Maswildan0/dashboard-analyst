"""
Financial Analyst Dashboard data models.

Design (per master development prompt #22-30):
- Master data: Campus, OrganizationUnit, FinancialPeriod, RevenueCategory, KpiTarget
- Fact tables: FinancialSummary, RevenueTransactionSummary
- All monetary values use DecimalField (never FloatField).
- Calculated KPIs (YoY, ratios, margins, achievements, composition) are NOT
  stored they are computed in the service layer from base data.
- Composite indexes on the fact tables for fast filter queries.
"""

from django.conf import settings
from django.db import models


class Campus(models.Model):
    """University campus (BDG/JKT/SBY/PWT)."""

    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f'{self.code} {self.name}'


class OrganizationUnit(models.Model):
    """Hierarchical organizational unit (faculty/directorate/cost/revenue/profit center)."""

    UNIT_TYPES = [
        ('FACULTY', 'Faculty'),
        ('DIRECTORATE', 'Directorate'),
        ('COST_CENTER', 'Cost Center'),
        ('REVENUE_CENTER', 'Revenue Center'),
        ('PROFIT_CENTER', 'Profit Center'),
        ('OTHER', 'Other'),
    ]

    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=150)
    campus = models.ForeignKey(Campus, on_delete=models.CASCADE, related_name='units')
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='children')
    unit_type = models.CharField(max_length=20, choices=UNIT_TYPES, default='OTHER')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f'{self.code} {self.name}'


class FinancialPeriod(models.Model):
    """Month-year period. Unique on (year, month)."""

    year = models.PositiveIntegerField()
    month = models.PositiveIntegerField()  # 1..12
    period_start = models.DateField()
    period_end = models.DateField()
    is_closed = models.BooleanField(default=False)

    class Meta:
        ordering = ['-year', '-month']
        constraints = [
            models.UniqueConstraint(fields=['year', 'month'], name='uniq_period_year_month'),
        ]

    def __str__(self):
        return f'{self.year}-{self.month:02d}'


class RevenueCategory(models.Model):
    """Revenue source category (TF, NTF_PROJECT, NTF_RESEARCH, ...).
    New categories can be added without schema changes."""

    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=100)
    category_type = models.CharField(max_length=30, blank=True, default='')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f'{self.code} {self.name}'


class FinancialSummary(models.Model):
    """Monthly financial fact: revenue/expense/SHU actual, target, budget."""

    period = models.ForeignKey(FinancialPeriod, on_delete=models.CASCADE, related_name='summaries')
    campus = models.ForeignKey(Campus, on_delete=models.CASCADE, related_name='summaries')
    organization_unit = models.ForeignKey(
        OrganizationUnit, null=True, blank=True, on_delete=models.CASCADE, related_name='summaries'
    )

    revenue_actual = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    revenue_target = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    expense_actual = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    expense_budget = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    shu_actual = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    shu_target = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        indexes = [
            models.Index(fields=['period', 'campus']),
            models.Index(fields=['period', 'campus', 'organization_unit']),
        ]

    def __str__(self):
        return f'{self.period} {self.campus.code} summary'


class RevenueTransactionSummary(models.Model):
    """Monthly revenue by category (TF / NTF_PROJECT / NTF_RESEARCH)."""

    period = models.ForeignKey(FinancialPeriod, on_delete=models.CASCADE, related_name='revenue_rows')
    campus = models.ForeignKey(Campus, on_delete=models.CASCADE, related_name='revenue_rows')
    organization_unit = models.ForeignKey(
        OrganizationUnit, null=True, blank=True, on_delete=models.CASCADE, related_name='revenue_rows'
    )
    revenue_category = models.ForeignKey(RevenueCategory, on_delete=models.CASCADE, related_name='revenue_rows')

    actual_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    target_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        indexes = [
            models.Index(fields=['period', 'campus']),
            models.Index(fields=['period', 'campus', 'organization_unit']),
            models.Index(fields=['revenue_category']),
        ]

    def __str__(self):
        return f'{self.period} {self.campus.code} {self.revenue_category.code}'


class KpiTarget(models.Model):
    """Standalone KPI targets (OPERATING_RATIO, SHU_MARGIN, ...)."""

    KPI_CODES = [
        ('REVENUE', 'Revenue'),
        ('EXPENSE', 'Expense'),
        ('SHU', 'SHU'),
        ('OPERATING_RATIO', 'Operating Ratio'),
        ('SHU_MARGIN', 'SHU Margin'),
        ('TF', 'Tuition Fee'),
        ('NTF_PROJECT', 'NTF Project'),
        ('NTF_RESEARCH', 'NTF Research'),
    ]

    year = models.PositiveIntegerField()
    campus = models.ForeignKey(Campus, null=True, blank=True, on_delete=models.CASCADE, related_name='kpi_targets')
    organization_unit = models.ForeignKey(
        OrganizationUnit, null=True, blank=True, on_delete=models.CASCADE, related_name='kpi_targets'
    )
    kpi_code = models.CharField(max_length=30, choices=KPI_CODES)
    target_value = models.DecimalField(max_digits=18, decimal_places=4)
    unit = models.CharField(max_length=20, default='%')

    class Meta:
        indexes = [models.Index(fields=['year', 'kpi_code'])]

    def __str__(self):
        return f'{self.year} {self.kpi_code} {self.target_value}{self.unit}'


class FinancialDataAuditLog(models.Model):
    """Audit trail for financial data changes."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=20)
    model = models.CharField(max_length=60)
    record_id = models.PositiveBigIntegerField(null=True, blank=True)
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.timestamp:%Y-%m-%d %H:%M} {self.user} {self.action} {self.model}'


# =====================================================================
# Revenue module models (SIMKUG-driven) added incrementally on top of
# the existing finance schema. Nothing below replaces existing tables.
# Principles:
#   * GL (actual), RKA (target), NTF report (project metadata) are kept
#     as SEPARATE sources; only joined in the analytics/service layer.
#   * account_code / pp_code are CharFields (leading-zero safe).
#   * Every GL row keeps its raw fields; classification NEVER falls back
#     to a default category unmapped stays NULL (UNMAPPED).
#   * Snapshot tables are the ONLY place derived/official closed numbers
#     are stored.
# =====================================================================


class RevenueAccount(models.Model):
    """Chart-of-accounts mapping: SIMKUG account code -> revenue category.

    account_code is the business identifier (never the name). An account
    with no (or expired) mapping is simply not present here GL rows that
    reference it keep revenue_account = NULL and surface as UNMAPPED.
    """

    account_code = models.CharField(max_length=40)
    account_name = models.CharField(max_length=200, blank=True, default='')
    revenue_category = models.ForeignKey(
        RevenueCategory, on_delete=models.PROTECT, related_name='accounts'
    )
    subcategory = models.CharField(max_length=80, blank=True, default='')
    # Expand-detail scope for this account's GL:
    #   PERIOD_ONLY  -> detail = exact selected month/year (periodic income,
    #                   e.g. Pend. Pendaftaran: one month's receipts)
    #   HISTORICAL   -> detail = full recognition history of the same
    #                   project/object up to the selected period (termin rows
    #                   from earlier months/years stay visible)
    DETAIL_HISTORY_MODES = [('PERIOD_ONLY', 'Period Only'), ('HISTORICAL', 'Historical')]
    detail_history_mode = models.CharField(
        max_length=20, choices=DETAIL_HISTORY_MODES, default='HISTORICAL')
    is_active = models.BooleanField(default=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['account_code']
        constraints = [
            models.UniqueConstraint(
                fields=['account_code', 'valid_from'], name='uniq_account_code_valid_from'
            ),
        ]
        indexes = [models.Index(fields=['account_code', 'is_active'])]

    def __str__(self):
        return f'{self.account_code} {self.account_name or self.revenue_category.code}'


class PPMaster(models.Model):
    """Cost-centre / work-order code (PP). CharField so leading zeros stay.

    One OrganizationUnit owns many PP. One PP can be used by MANY projects
    (PP != project id), so projects reference PP separately.
    """

    pp_code = models.CharField(max_length=20, unique=True)
    organization_unit = models.ForeignKey(
        OrganizationUnit, null=True, blank=True, on_delete=models.SET_NULL, related_name='pp_codes'
    )
    is_active = models.BooleanField(default=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['pp_code']

    def __str__(self):
        return f'{self.pp_code}'


class RkaVersion(models.Model):
    """RKA revisions (Awal / Perubahan). Old versions are never overwritten."""

    STATUSES = [
        ('DRAFT', 'Draft'),
        ('ACTIVE', 'Active'),
        ('SUPERSEDED', 'Superseded'),
    ]

    year = models.PositiveIntegerField()
    version_code = models.CharField(max_length=30)
    version_name = models.CharField(max_length=150, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUSES, default='DRAFT')
    effective_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['year', '-effective_date']

    def __str__(self):
        return f'{self.year} {self.version_code}'


class RevenueBudget(models.Model):
    """Annual RKA at grain RKA version x year x PP x revenue account."""

    rka_version = models.ForeignKey(RkaVersion, on_delete=models.CASCADE, related_name='budgets')
    year = models.PositiveIntegerField()
    pp = models.ForeignKey(PPMaster, on_delete=models.CASCADE, related_name='budgets')
    revenue_account = models.ForeignKey(
        RevenueAccount, on_delete=models.CASCADE, related_name='budgets'
    )
    annual_budget = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        ordering = ['year']
        constraints = [
            models.UniqueConstraint(
                fields=['rka_version', 'year', 'pp', 'revenue_account'],
                name='uniq_rka_version_year_pp_account',
            ),
        ]
        indexes = [
            models.Index(fields=['year', 'pp', 'revenue_account']),
        ]

    def __str__(self):
        return f'{self.year} {self.pp} {self.revenue_account}'


class RevenueBudgetMonthly(models.Model):
    """Monthly phasing of an annual RKA. Grain: revenue_budget x month."""

    revenue_budget = models.ForeignKey(
        RevenueBudget, on_delete=models.CASCADE, related_name='monthly_rows'
    )
    month = models.PositiveIntegerField()  # 1..12
    budget_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        ordering = ['month']
        constraints = [
            models.UniqueConstraint(
                fields=['revenue_budget', 'month'], name='uniq_revenue_budget_month'
            ),
        ]

    def __str__(self):
        return f'{self.revenue_budget} M{self.month}'


class RevenueLedger(models.Model):
    """Transaction-level General Ledger revenue rows from SIMKUG.

    RAW fields keep the source values verbatim; NORMALIZED relations point
    to masters when a mapping exists, otherwise stay NULL (UNMAPPED).
    Actual revenue is derived from debit/credit with a configurable
    convention (see revenue_service) never from source_balance.
    """

    # --- stable source identity (upsert key; §6) ---
    source_transaction_id = models.CharField(max_length=64, blank=True, default='')
    source_line_id = models.CharField(max_length=64, blank=True, default='')

    # --- when + where ---
    posting_date = models.DateField(null=True, blank=True)
    period = models.ForeignKey(
        FinancialPeriod, on_delete=models.PROTECT, related_name='revenue_ledger_rows'
    )
    voucher_number = models.CharField(max_length=60, blank=True, default='')
    document_number = models.CharField(max_length=60, blank=True, default='')

    # --- raw source fields ---
    account_code_raw = models.CharField(max_length=40, blank=True, default='')
    account_name_raw = models.CharField(max_length=200, blank=True, default='')
    description_raw = models.TextField(blank=True, default='')
    pp_code_raw = models.CharField(max_length=20, blank=True, default='')

    # --- normalized relations (nullable = UNMAPPED) ---
    revenue_account = models.ForeignKey(
        RevenueAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name='ledger_rows'
    )
    pp = models.ForeignKey(
        PPMaster, null=True, blank=True, on_delete=models.SET_NULL, related_name='ledger_rows'
    )
    description_normalized = models.TextField(blank=True, default='')

    # --- financials (Decimal; never float) ---
    debit = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    source_balance = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)

    # --- system ---
    source_updated_at = models.DateTimeField(null=True, blank=True)
    ingested_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['posting_date', 'id']
        constraints = [
            # Primary upsert key when SIMKUG provides stable ids.
            models.UniqueConstraint(
                fields=['source_transaction_id', 'source_line_id'],
                condition=models.Q(source_transaction_id__gt=''),
                name='uniq_ledger_source_tx_line',
            ),
        ]
        indexes = [
            models.Index(fields=['posting_date']),
            models.Index(fields=['period']),
            models.Index(fields=['pp']),
            models.Index(fields=['revenue_account']),
            models.Index(fields=['source_transaction_id']),
        ]

    def __str__(self):
        return f'{self.period} {self.account_code_raw} #{self.pk}'


class Project(models.Model):
    """NTF project master. Metadata comes from the SIMKUG NTF report; the
    authoritative revenue numbers do NOT (they come from mapped GL)."""

    project_number = models.CharField(max_length=60, blank=True, default='')
    pp = models.ForeignKey(PPMaster, null=True, blank=True, on_delete=models.SET_NULL, related_name='projects')
    contract_code = models.CharField(max_length=60, blank=True, default='')
    project_name = models.CharField(max_length=300, blank=True, default='')
    organization_unit = models.ForeignKey(
        OrganizationUnit, null=True, blank=True, on_delete=models.SET_NULL, related_name='projects'
    )
    campus = models.ForeignKey(Campus, null=True, blank=True, on_delete=models.SET_NULL, related_name='projects')
    project_value = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    first_seen_period = models.ForeignKey(
        FinancialPeriod, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    last_seen_period = models.ForeignKey(
        FinancialPeriod, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    source_status = models.CharField(max_length=40, blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['project_number']
        indexes = [
            models.Index(fields=['project_number']),
            models.Index(fields=['pp']),
        ]

    def __str__(self):
        return self.project_name or self.project_number or f'Project #{self.pk}'


class NtfReportSnapshot(models.Model):
    """Raw NTF report rows, kept for audit/reconciliation. NEVER overwritten 
    each load appends a new snapshot of the historical report position."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='ntf_snapshots')
    period = models.ForeignKey(FinancialPeriod, on_delete=models.PROTECT, related_name='ntf_snapshots')
    source_project_value = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    source_total_recognized = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    source_current_year_recognized = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    unit_raw = models.CharField(max_length=200, blank=True, default='')
    organization_raw = models.CharField(max_length=200, blank=True, default='')
    project_name_raw = models.CharField(max_length=300, blank=True, default='')
    contract_code_raw = models.CharField(max_length=60, blank=True, default='')
    loaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-loaded_at']
        indexes = [models.Index(fields=['project', 'period'])]

    def __str__(self):
        return f'NTF {self.period} {self.project}'


class ProjectAlias(models.Model):
    """Aliases learned from GL descriptions so later matching improves."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='aliases')
    pp = models.ForeignKey(PPMaster, null=True, blank=True, on_delete=models.SET_NULL, related_name='project_aliases')
    alias_raw = models.CharField(max_length=300)
    alias_normalized = models.CharField(max_length=300, blank=True, default='')
    source = models.CharField(max_length=30, default='GL')
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_verified', 'alias_normalized']

    def __str__(self):
        return f'{self.project} ~ {self.alias_raw}'


class GLProjectMapping(models.Model):
    """Bridge GL row -> project. An unmapped GL row is NOT deleted from the
    revenue total; it simply has no mapping row (or one with UNMATCHED)."""

    MATCH_STATUSES = [
        ('AUTO_MATCHED', 'Auto Matched'),
        ('VERIFIED', 'Verified'),
        ('NEEDS_REVIEW', 'Needs Review'),
        ('UNMATCHED', 'Unmatched'),
    ]

    ledger = models.ForeignKey(RevenueLedger, on_delete=models.CASCADE, related_name='project_mappings')
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL, related_name='gl_mappings')
    allocated_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    match_method = models.CharField(max_length=30, blank=True, default='')
    match_confidence = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    match_status = models.CharField(max_length=20, choices=MATCH_STATUSES, default='UNMATCHED')
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['ledger']),
            models.Index(fields=['project']),
            models.Index(fields=['match_status']),
        ]

    def __str__(self):
        return f'{self.ledger} -> {self.project}'


class ProjectMonthlySnapshot(models.Model):
    """Frozen per-project revenue position at month close."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='monthly_snapshots')
    period = models.ForeignKey(FinancialPeriod, on_delete=models.CASCADE, related_name='project_monthly_snapshots')

    opening_ytd = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    recognized_month = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    closing_ytd = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    opening_lifetime = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    closing_lifetime = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    project_value = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    remaining_value = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    status_at_close = models.CharField(max_length=30, blank=True, default='')
    is_frozen = models.BooleanField(default=True)
    frozen_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['project', 'period'], name='uniq_project_monthly_snapshot'),
        ]
        indexes = [models.Index(fields=['period'])]

    def __str__(self):
        return f'{self.period} {self.project}'


class RevenueMonthlySnapshot(models.Model):
    """Frozen monthly revenue position at grain period x PP x account.
    Category/Organization are derivable (account->category, pp->org)."""

    period = models.ForeignKey(FinancialPeriod, on_delete=models.CASCADE, related_name='revenue_monthly_snapshots')
    pp = models.ForeignKey(PPMaster, null=True, blank=True, on_delete=models.CASCADE, related_name='revenue_monthly_snapshots')
    revenue_account = models.ForeignKey(
        RevenueAccount, on_delete=models.CASCADE, related_name='revenue_monthly_snapshots'
    )
    actual_amount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    is_frozen = models.BooleanField(default=True)
    frozen_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['period', 'pp', 'revenue_account'], name='uniq_revenue_monthly_snapshot'
            ),
        ]
        indexes = [
            models.Index(fields=['period', 'pp', 'revenue_account']),
        ]

    def __str__(self):
        return f'{self.period} {self.pp or "-"} {self.revenue_account}'


class SimkugSyncLog(models.Model):
    """One row per SIMKUG sync run (data-quality + last-sync display)."""

    SYNC_TYPES = [
        ('GL', 'General Ledger'),
        ('NTF', 'NTF Report'),
        ('RKA', 'RKA'),
    ]
    STATUSES = [
        ('RUNNING', 'Running'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
        ('PARTIAL', 'Partial'),
    ]

    sync_type = models.CharField(max_length=10, choices=SYNC_TYPES)
    status = models.CharField(max_length=10, choices=STATUSES, default='RUNNING')
    period = models.ForeignKey(FinancialPeriod, null=True, blank=True, on_delete=models.SET_NULL)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    rows_processed = models.PositiveIntegerField(default=0)
    rows_upserted = models.PositiveIntegerField(default=0)
    message = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-started_at']
        indexes = [models.Index(fields=['sync_type', 'status'])]

    def __str__(self):
        return f'{self.sync_type} {self.started_at:%Y-%m-%d %H:%M} {self.status}'
