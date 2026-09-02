from django.contrib import admin

from .models import (
    Campus,
    FinancialDataAuditLog,
    FinancialPeriod,
    FinancialSummary,
    KpiTarget,
    OrganizationUnit,
    RevenueCategory,
    RevenueTransactionSummary,
)


@admin.register(Campus)
class CampusAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'is_active')


@admin.register(OrganizationUnit)
class OrganizationUnitAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'campus', 'unit_type', 'is_active')
    list_filter = ('unit_type', 'campus')


@admin.register(FinancialPeriod)
class FinancialPeriodAdmin(admin.ModelAdmin):
    list_display = ('year', 'month', 'period_start', 'period_end', 'is_closed')
    list_filter = ('year', 'is_closed')


@admin.register(RevenueCategory)
class RevenueCategoryAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'category_type', 'is_active')


@admin.register(FinancialSummary)
class FinancialSummaryAdmin(admin.ModelAdmin):
    list_display = ('period', 'campus', 'organization_unit', 'revenue_actual', 'expense_actual', 'shu_actual')
    list_filter = ('period__year', 'campus')


@admin.register(RevenueTransactionSummary)
class RevenueTransactionSummaryAdmin(admin.ModelAdmin):
    list_display = ('period', 'campus', 'revenue_category', 'actual_amount', 'target_amount')
    list_filter = ('period__year', 'campus', 'revenue_category')


@admin.register(KpiTarget)
class KpiTargetAdmin(admin.ModelAdmin):
    list_display = ('year', 'kpi_code', 'campus', 'target_value', 'unit')
    list_filter = ('year', 'kpi_code')


@admin.register(FinancialDataAuditLog)
class FinancialDataAuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'action', 'model', 'record_id')
    readonly_fields = ('timestamp',)
