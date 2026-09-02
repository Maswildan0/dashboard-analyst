"""
Financial Analyst Dashboard data models.

Design (per master development prompt #22-30):
- Master data: Campus, OrganizationUnit, FinancialPeriod, RevenueCategory, KpiTarget
- Fact tables: FinancialSummary, RevenueTransactionSummary
- All monetary values use DecimalField (never FloatField).
- Calculated KPIs (YoY, ratios, margins, achievements, composition) are NOT
  stored — they are computed in the service layer from base data.
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
        return f'{self.code} — {self.name}'


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
        return f'{self.code} — {self.name}'


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
        return f'{self.code} — {self.name}'


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
