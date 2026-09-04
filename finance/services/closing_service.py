"""Month-closing: freeze revenue position atomically.

close_revenue_period(period):
  1. validate period is OPEN (no-op if already closed / no double snapshot)
  2. compute final revenue position from the LIVE ledger
  3. write RevenueMonthlySnapshot (period x pp x account)
  4. write ProjectMonthlySnapshot per project (YTD/lifetime/remaining)
  5. set is_closed = True
  6. audit log

Re-running after close returns immediately (idempotent).
"""
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from finance.models import (
    FinancialDataAuditLog,
    GLProjectMapping,
    Project,
    ProjectMonthlySnapshot,
    RevenueLedger,
    RevenueMonthlySnapshot,
)

ZERO = Decimal('0')


def _net(row):
    # mirrors revenue_service sign convention (credit - debit)
    return row.credit - row.debit


@transaction.atomic
def close_revenue_period(period, user=None, force=False):
    if period.is_closed:
        if not force:
            return {'status': 'ALREADY_CLOSED', 'period': str(period)}
        # allow recompute (idempotent via get_or_create/update)
    if not force and period.month != date.today().month or period.year != date.today().year:
        # allow closing historical open months too; skip date guard
        pass

    # --- 1. aggregate ledger into monthly snapshots (period x pp x account) ---
    rows = RevenueLedger.objects.filter(period=period).select_related('pp', 'revenue_account')
    agg = {}
    for row in rows.iterator(chunk_size=1000):
        if row.revenue_account_id is None:
            continue  # unmapped accounts are excluded from per-account snapshot
        key = (row.pp_id, row.revenue_account_id)
        agg[key] = agg.get(key, ZERO) + _net(row)

    RevenueMonthlySnapshot.objects.filter(period=period).delete()
    for (pp_id, acc_id), amount in agg.items():
        RevenueMonthlySnapshot.objects.create(
            period=period, pp_id=pp_id, revenue_account_id=acc_id,
            actual_amount=amount, is_frozen=True, frozen_at=timezone.now(),
        )

    # --- 2. project monthly snapshots (YTD/lifetime from mapped GL) ---
    projects = Project.objects.filter(
        id__in=GLProjectMapping.objects.filter(ledger__period=period)
                       .values('project_id').distinct()
    )
    for project in projects:
        mappings = GLProjectMapping.objects.filter(project=project, ledger__period=period)
        month_amount = ZERO
        for m in mappings.select_related('ledger').iterator(chunk_size=500):
            month_amount += _net(m.ledger)

        lifetime_before = ZERO
        # lifetime = all mapped GL for the project up to & incl this period
        all_maps = GLProjectMapping.objects.filter(project=project)
        for m in all_maps.select_related('ledger').iterator(chunk_size=500):
            lifetime_before += _net(m.ledger)

        ytd_open = ZERO
        for m in GLProjectMapping.objects.filter(
                project=project, ledger__period__year=period.year,
                ledger__period__month__lte=period.month).select_related('ledger').iterator(chunk_size=500):
            ytd_open += _net(m.ledger)

        prev_snap = ProjectMonthlySnapshot.objects.filter(project=project, period__lt=period).order_by('-period__year', '-period__month').first()
        opening_lifetime = prev_snap.closing_lifetime if prev_snap else (lifetime_before - month_amount)
        opening_ytd = prev_snap.closing_ytd if prev_snap and prev_snap.period.year == period.year else ZERO
        closing_ytd = opening_ytd + month_amount
        closing_lifetime = opening_lifetime + month_amount
        project_value = project.project_value
        remaining = project_value - closing_lifetime
        if closing_lifetime == ZERO:
            status = 'NO_REVENUE'
        elif closing_lifetime < project_value:
            status = 'ON_PROGRESS'
        elif closing_lifetime == project_value:
            status = 'FULLY_RECOGNIZED'
        else:
            status = 'NEEDS_REVIEW'

        ProjectMonthlySnapshot.objects.update_or_create(
            project=project, period=period,
            defaults={
                'opening_ytd': opening_ytd,
                'recognized_month': month_amount,
                'closing_ytd': closing_ytd,
                'opening_lifetime': opening_lifetime,
                'closing_lifetime': closing_lifetime,
                'project_value': project_value,
                'remaining_value': remaining,
                'status_at_close': status,
                'is_frozen': True,
                'frozen_at': timezone.now(),
            },
        )

    # --- 3. close + audit ---
    period.is_closed = True
    period.save(update_fields=['is_closed'])
    FinancialDataAuditLog.objects.create(
        user=user, action='CLOSE', model='FinancialPeriod',
        record_id=period.pk,
        new_value={'year': period.year, 'month': period.month, 'is_closed': True},
    )
    return {'status': 'CLOSED', 'period': str(period)}
