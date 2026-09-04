"""Sync SIMKUG feeds for a period/year (idempotent, OPEN-only by default).

Run:
    python manage.py sync_simkug --year 2026 --month 8
    python manage.py sync_simkug --year 2026 --rka --force
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from finance.integrations.simkug_sync import sync_general_ledger, sync_ntf_report, sync_rka
from finance.models import SimkugSyncLog


class Command(BaseCommand):
    help = 'Sync SIMKUG feeds (GL / RKA) into the revenue database.'

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int)
        parser.add_argument('--month', type=int)
        parser.add_argument('--rka', action='store_true', help='sync RKA instead of GL')
        parser.add_argument('--ntf', action='store_true', help='sync NTF project report instead of GL')
        parser.add_argument('--force', action='store_true', help='allow closed-period resync')

    def handle(self, *args, **opts):
        year = opts['year']
        month = opts['month']
        if year is None:
            from finance.models import FinancialPeriod
            latest = FinancialPeriod.objects.order_by('-year', '-month').first()
            year = latest.year if latest else 2026
        if month is None:
            month = 8

        if opts['ntf']:
            mark = SimkugSyncLog.objects.create(sync_type='NTF', status='RUNNING')
            try:
                processed, inserted, updated = sync_ntf_report(year, month, mark=mark)
                mark.status = 'SUCCESS'; mark.rows_processed = processed
                mark.rows_upserted = inserted + updated
                mark.finished_at = timezone.now(); mark.save()
                self.stdout.write(self.style.SUCCESS(f'NTF {year}-{month:02d}: {processed} rows, {inserted} new, {updated} updated'))
            except Exception as exc:
                mark.status = 'FAILED'; mark.message = str(exc)
                mark.finished_at = timezone.now(); mark.save()
                raise
        elif opts['rka']:
            mark = SimkugSyncLog.objects.create(sync_type='RKA', status='RUNNING')
            try:
                processed, inserted, updated = sync_rka(year, mark=mark)
                mark.status = 'SUCCESS'; mark.rows_processed = processed
                mark.rows_upserted = inserted + updated
                mark.finished_at = timezone.now(); mark.save()
                self.stdout.write(self.style.SUCCESS(f'RKA {year}: {processed} rows, {inserted} new, {updated} updated'))
            except Exception as exc:
                mark.status = 'FAILED'; mark.message = str(exc)
                mark.finished_at = timezone.now(); mark.save()
                raise
        else:
            mark = SimkugSyncLog.objects.create(sync_type='GL', status='RUNNING', period_id=None)
            try:
                from finance.models import FinancialPeriod
                period = FinancialPeriod.objects.filter(year=year, month=month).first()
                if period:
                    mark.period = period
                mark.save()
                processed, inserted, updated = sync_general_ledger(year, month, force=opts['force'], mark=mark)
                if mark.status != 'PARTIAL':
                    mark.status = 'SUCCESS'
                mark.rows_processed = processed
                mark.rows_upserted = inserted + updated
                mark.finished_at = timezone.now(); mark.save()
                self.stdout.write(self.style.SUCCESS(f'GL {year}-{month:02d}: {processed} rows, {inserted} new, {updated} updated'))
            except Exception as exc:
                mark.status = 'FAILED'; mark.message = str(exc)
                mark.finished_at = timezone.now(); mark.save()
                raise
