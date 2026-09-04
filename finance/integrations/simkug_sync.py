"""SIMKUG ingestion orchestrator.

Design:
- GL upsert for OPEN periods only (closed periods are frozen; re-sync only
  with force=True).
- Stable identity first: (source_transaction_id, source_line_id). When the
  API gives no stable id the caller can set USE_COMPOSITE_FALLBACK=1 to key
  on (posting_date, voucher_number, document_number, debit, credit).
- Idempotent: same key + same values => no-op; changed values => UPDATE.
- Raw fields always stored; account/pp resolution keeps NULL (UNMAPPED)
  when no mapping exists never a default category.
"""
import os
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from finance.models import (
    FinancialPeriod,
    NtfReportSnapshot,
    OrganizationUnit,
    PPMaster,
    Project,
    RevenueAccount,
    RevenueBudget,
    RevenueBudgetMonthly,
    RevenueCategory,
    RevenueLedger,
    RkaVersion,
    SimkugSyncLog,
)
from finance.services.account_classification import normalize_description

from . import simkug_client


def _dec(v):
    if v in (None, ''):
        return Decimal('0')
    return Decimal(str(v))


def _get_or_create_period(year, month):
    period, _ = FinancialPeriod.objects.get_or_create(
        year=year,
        month=month,
        defaults={
            'period_start': date(year, month, 1),
            'period_end': date(year, month, 28),  # corrected below
        },
    )
    if period.period_start != date(year, month, 1):
        period.period_start = date(year, month, 1)
        period.save(update_fields=['period_start'])
    return period


def _composite_fallback_enabled():
    return os.environ.get('SIMKUG_COMPOSITE_FALLBACK', '0') == '1'


def _ledger_key(row):
    tx = (row.get('transaction_id') or '').strip()
    line = (row.get('line_id') or '').strip()
    if tx and not _composite_fallback_enabled():
        return {'source_transaction_id': tx, 'source_line_id': line}
    return {
        'posting_date': row.get('posting_date'),
        'voucher_number': (row.get('voucher_number') or '').strip(),
        'document_number': (row.get('document_number') or '').strip(),
        'debit': _dec(row.get('debit')),
        'credit': _dec(row.get('credit')),
    }


def sync_general_ledger(year, month, *, force=False, mark=None):
    """Upsert GL rows for one period. Returns (processed, inserted, updated)."""
    period = _get_or_create_period(year, month)
    if period.is_closed and not force:
        if mark:
            mark.status = 'PARTIAL'
            mark.message = f'period {period} closed; skipped (use --force)'
            mark.finished_at = timezone.now()
            mark.save(update_fields=['status', 'message', 'finished_at'])
        return 0, 0, 0

    rows = list(simkug_client.fetch_general_ledger(period.period_start, period.period_end))
    processed = inserted = updated = 0

    with transaction.atomic():
        for row in rows:
            processed += 1
            key = _ledger_key(row)
            account, _status = _resolve_account(row)
            pp = _resolve_pp(row)
            values = {
                'period': period,
                'posting_date': row.get('posting_date') or period.period_start,
                'voucher_number': (row.get('voucher_number') or '').strip(),
                'document_number': (row.get('document_number') or '').strip(),
                'account_code_raw': (row.get('account_code') or '').strip(),
                'account_name_raw': (row.get('account_name') or '').strip(),
                'description_raw': (row.get('description') or '').strip(),
                'pp_code_raw': (row.get('pp_code') or '').strip(),
                'revenue_account': account,
                'pp': pp,
                'description_normalized': normalize_description(row.get('description') or ''),
                'debit': _dec(row.get('debit')),
                'credit': _dec(row.get('credit')),
                'source_balance': _dec(row.get('balance')) if row.get('balance') not in (None, '') else None,
                'source_updated_at': row.get('source_updated_at') or None,
            }
            # Normalize date/datetime carriers so re-syncs compare equal.
            raw_pd = values['posting_date']
            if not hasattr(raw_pd, 'strftime'):
                from datetime import datetime as _dt
                try:
                    values['posting_date'] = _dt.strptime(str(raw_pd)[:10], '%Y-%m-%d').date()
                except ValueError:
                    values['posting_date'] = period.period_start
            raw_su = values.get('source_updated_at')
            if raw_su and not hasattr(raw_su, 'isoformat'):
                from django.utils.dateparse import parse_datetime, parse_date
                values['source_updated_at'] = parse_datetime(str(raw_su)) or parse_date(str(raw_su))
            existing = RevenueLedger.objects.filter(**key).first()
            if existing is None:
                RevenueLedger.objects.create(source_transaction_id=key.get('source_transaction_id', ''),
                                             source_line_id=key.get('source_line_id', ''),
                                             **{k: v for k, v in values.items() if k not in ('source_transaction_id', 'source_line_id')})
                inserted += 1
            else:
                def _cmp(existing_value, new_value):
                    if existing_value == new_value:
                        return False
                    # date/datetime coercion: stored aware datetimes vs naive dates
                    try:
                        if existing_value is not None and new_value is not None and hasattr(existing_value, 'date') and hasattr(new_value, 'date'):
                            return existing_value.date() != new_value.date() or (hasattr(existing_value, 'hour') != hasattr(new_value, 'hour'))
                    except (TypeError, ValueError):
                        pass
                    return True
                changed = any(_cmp(getattr(existing, f), v) for f, v in values.items() if hasattr(existing, f))
                if changed:
                    for f, v in values.items():
                        setattr(existing, f, v)
                    existing.save()
                    updated += 1
    return processed, inserted, updated


def _resolve_account(row):
    from finance.services.account_classification import classify_account
    return classify_account(row.get('account_code') or '')


def _resolve_pp(row):
    code = (row.get('pp_code') or '').strip()
    if not code:
        return None
    return PPMaster.objects.filter(pp_code=code, is_active=True).first()


def sync_rka(year, *, version_code='AWAL', version_name='RKA Awal', mark=None):
    """Upsert RKA (annual + monthly phasing) for a year."""
    rows = list(simkug_client.fetch_revenue_rka(year))
    version, _ = RkaVersion.objects.get_or_create(
        year=year, version_code=version_code,
        defaults={'version_name': version_name, 'status': 'ACTIVE', 'is_active': True},
    )
    processed = inserted = updated = 0
    with transaction.atomic():
        for row in rows:
            processed += 1
            pp = _resolve_pp(row)
            account = RevenueAccount.objects.filter(account_code=row.get('account_code'), is_active=True).first()
            if pp is None or account is None:
                continue  # unmapped RKA is skipped (never guessed)
            budget, created = RevenueBudget.objects.update_or_create(
                rka_version=version, year=year, pp=pp, revenue_account=account,
                defaults={'annual_budget': _dec(row.get('annual_budget'))},
            )
            if created:
                inserted += 1
            elif budget.annual_budget != _dec(row.get('annual_budget')):
                updated += 1
            phasing = row.get('monthly_phasing') or []
            for m, amount in enumerate(phasing, start=1):
                RevenueBudgetMonthly.objects.update_or_create(
                    revenue_budget=budget, month=m,
                    defaults={'budget_amount': _dec(amount)},
                )
    return processed, inserted, updated


def sync_ntf_report(year, month, *, mark=None):
    """Upsert Project masters from NTF report rows + append raw snapshots
    (snapshots are append-only; masters update in place)."""
    rows = list(simkug_client.fetch_ntf_report(year, month))
    period = _get_or_create_period(year, month)
    processed = inserted = updated = 0
    with transaction.atomic():
        for row in rows:
            processed += 1
            pp = _resolve_pp(row)
            org = None
            if pp is not None:
                org = pp.organization_unit
            elif row.get('organization'):
                org = OrganizationUnit.objects.filter(name=row['organization']).first()
            proj, created = Project.objects.update_or_create(
                project_number=(row.get('project_number') or '').strip(),
                defaults={
                    'pp': pp,
                    'contract_code': (row.get('contract_code') or '').strip(),
                    'project_name': (row.get('project_name') or '').strip(),
                    'organization_unit': org,
                    'project_value': _dec(row.get('project_value')),
                    'source_status': (row.get('source_status') or 'ACTIVE'),
                    'last_seen_period': period,
                    'is_active': True,
                },
            )
            if created:
                proj.first_seen_period = period
                proj.save(update_fields=['first_seen_period'])
                inserted += 1
            else:
                updated += 1
            # append-only raw snapshot (historical report position preserved)
            NtfReportSnapshot.objects.create(
                project=proj, period=period,
                source_project_value=_dec(row.get('project_value')) if row.get('project_value') not in (None, '') else None,
                source_total_recognized=_dec(row.get('total_recognized')) if row.get('total_recognized') not in (None, '') else None,
                source_current_year_recognized=_dec(row.get('current_year_recognized')) if row.get('current_year_recognized') not in (None, '') else None,
                unit_raw=(row.get('unit') or '').strip(),
                organization_raw=(row.get('organization') or '').strip(),
                project_name_raw=(row.get('project_name') or '').strip(),
                contract_code_raw=(row.get('contract_code') or '').strip(),
            )
    return processed, inserted, updated
