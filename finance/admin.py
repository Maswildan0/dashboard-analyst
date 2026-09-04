from django.contrib import admin

from .models import (
    Campus,
    FinancialDataAuditLog,
    FinancialPeriod,
    FinancialSummary,
    GLProjectMapping,
    KpiTarget,
    NtfReportSnapshot,
    OrganizationUnit,
    PPMaster,
    Project,
    ProjectAlias,
    ProjectMonthlySnapshot,
    RevenueAccount,
    RevenueBudget,
    RevenueBudgetMonthly,
    RevenueCategory,
    RevenueLedger,
    RevenueMonthlySnapshot,
    RevenueTransactionSummary,
    RkaVersion,
    SimkugSyncLog,
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


# ---------------- Revenue module (SIMKUG-driven) ----------------

@admin.register(RevenueAccount)
class RevenueAccountAdmin(admin.ModelAdmin):
    list_display = ('account_code', 'account_name', 'revenue_category', 'subcategory', 'is_active', 'valid_from', 'valid_to')
    list_filter = ('revenue_category', 'is_active')
    search_fields = ('account_code', 'account_name')


@admin.register(PPMaster)
class PPMasterAdmin(admin.ModelAdmin):
    list_display = ('pp_code', 'organization_unit', 'is_active', 'valid_from', 'valid_to')
    list_filter = ('organization_unit', 'is_active')
    search_fields = ('pp_code',)


@admin.register(RkaVersion)
class RkaVersionAdmin(admin.ModelAdmin):
    list_display = ('year', 'version_code', 'version_name', 'status', 'effective_date', 'is_active')
    list_filter = ('year', 'status')


@admin.register(RevenueBudget)
class RevenueBudgetAdmin(admin.ModelAdmin):
    list_display = ('year', 'pp', 'revenue_account', 'annual_budget', 'rka_version')
    list_filter = ('year', 'rka_version')
    search_fields = ('pp__pp_code', 'revenue_account__account_code')


@admin.register(RevenueBudgetMonthly)
class RevenueBudgetMonthlyAdmin(admin.ModelAdmin):
    list_display = ('revenue_budget', 'month', 'budget_amount')


@admin.register(RevenueLedger)
class RevenueLedgerAdmin(admin.ModelAdmin):
    list_display = ('posting_date', 'period', 'account_code_raw', 'account_name_raw', 'credit', 'debit', 'revenue_account', 'pp')
    list_filter = ('period__year', 'period__month', 'revenue_account__revenue_category')
    search_fields = ('voucher_number', 'document_number', 'description_raw', 'account_code_raw')
    readonly_fields = ('ingested_at', 'created_at', 'updated_at')


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('project_number', 'project_name', 'pp', 'organization_unit', 'project_value', 'is_active')
    list_filter = ('is_active', 'pp__organization_unit')
    search_fields = ('project_number', 'project_name')


@admin.register(NtfReportSnapshot)
class NtfReportSnapshotAdmin(admin.ModelAdmin):
    list_display = ('period', 'project', 'source_project_value', 'source_total_recognized', 'loaded_at')
    list_filter = ('period__year',)


@admin.register(ProjectAlias)
class ProjectAliasAdmin(admin.ModelAdmin):
    list_display = ('project', 'alias_raw', 'is_verified', 'source')
    list_filter = ('is_verified',)


@admin.register(GLProjectMapping)
class GLProjectMappingAdmin(admin.ModelAdmin):
    list_display = ('ledger', 'project', 'allocated_amount', 'match_method', 'match_confidence', 'match_status', 'verified_by')
    list_filter = ('match_status', 'ledger__period__year')
    search_fields = ('ledger__description_raw', 'project__project_name')
    actions = ['mark_verified']

    @admin.action(description='Mark selected as VERIFIED')
    def mark_verified(self, request, queryset):
        queryset.update(match_status='VERIFIED')


@admin.register(RevenueMonthlySnapshot)
class RevenueMonthlySnapshotAdmin(admin.ModelAdmin):
    list_display = ('period', 'pp', 'revenue_account', 'actual_amount', 'is_frozen')
    list_filter = ('period__year',)


@admin.register(ProjectMonthlySnapshot)
class ProjectMonthlySnapshotAdmin(admin.ModelAdmin):
    list_display = ('period', 'project', 'closing_ytd', 'closing_lifetime', 'remaining_value', 'status_at_close')
    list_filter = ('period__year', 'status_at_close')


@admin.register(SimkugSyncLog)
class SimkugSyncLogAdmin(admin.ModelAdmin):
    list_display = ('sync_type', 'period', 'status', 'rows_processed', 'rows_upserted', 'started_at', 'finished_at')
    list_filter = ('sync_type', 'status')
    readonly_fields = ('started_at',)
