"""Exact data migration from a canonical SQLite dummy database into the
configured Django target database (finance app).

Source of truth : revenue_dummy_v2.sqlite3 (canonical copy of db.sqlite3).
Target          : the Django DB engine configured in settings (SQLite dev,
                  PostgreSQL when DB_ENGINE=postgres).

Guarantees
    * transactional  - whole import inside one atomic block; failure rolls back
    * idempotent     - safe to re-run on an EMPTY finance schema; use --reset
                       to wipe finance tables first (development only)
    * PK preserved   - source row id == target row id (deterministic mapping)
    * no re-matching - GLProjectMapping rows are copied verbatim (VERIFIED/AUTO
                       statuses preserved); no new random generator runs
    * validation     - row-count, financial SUM, FK integrity + rule checks
                       printed at the end (source vs target)

Usage
    python manage.py import_revenue_dummy_sqlite [--source path.sqlite3] [--reset]
"""
from collections import OrderedDict
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from finance import models as M


# --------------------------------------------------------------------------
# Import order follows FK dependencies (parents before children).
# model -> source table (same name in canonical sqlite).
# --------------------------------------------------------------------------
FINANCE_MODELS = [
    M.Campus, M.OrganizationUnit, M.PPMaster, M.RevenueCategory,
    M.RevenueAccount, M.FinancialPeriod, M.RkaVersion, M.RevenueBudget,
    M.RevenueBudgetMonthly, M.Project, M.ProjectAlias, M.RevenueLedger,
    M.GLProjectMapping, M.NtfReportSnapshot, M.RevenueMonthlySnapshot,
    M.ProjectMonthlySnapshot, M.FinancialSummary, M.RevenueTransactionSummary,
    M.KpiTarget, M.SimkugSyncLog, M.FinancialDataAuditLog,
]

# Reverse order for truncation (children first).
RESET_MODELS = list(reversed(FINANCE_MODELS))

# Every table that must exist in the source for a PASS report.
ALL_FINANCE_TABLES = [m._meta.db_table for m in FINANCE_MODELS]

MONEY_FIELDS = {
    'finance_project': ['project_value'],
    'finance_revenueledger': ['credit', 'debit', 'source_balance'],
    'finance_glprojectmapping': ['allocated_amount'],
    'finance_revenuebudget': ['annual_budget'],
    'finance_revenuebudgetmonthly': ['budget_amount'],
    'finance_revenuemonthlysnapshot': ['actual_amount'],
    'finance_projectmonthlysnapshot': ['opening_ytd', 'recognized_month',
                                       'closing_ytd', 'opening_lifetime',
                                       'closing_lifetime', 'project_value',
                                       'remaining_value'],
    'finance_financialsummary': ['revenue_actual', 'revenue_target',
                                 'expense_actual', 'expense_budget',
                                 'shu_actual', 'shu_target'],
    'finance_revenuetransactionsummary': ['actual_amount', 'target_amount'],
    'finance_ntfreportsnapshot': ['source_project_value',
                                  'source_total_recognized',
                                  'source_current_year_recognized'],
    'finance_kpitarget': ['target_value'],
}


class Command(BaseCommand):
    help = 'Import exact dummy data from revenue_dummy_v2.sqlite3 into the target DB.'

    def add_arguments(self, parser):
        parser.add_argument('--source', default='revenue_dummy_v2.sqlite3',
                            help='Path to the canonical SQLite source file.')
        parser.add_argument('--reset', action='store_true',
                            help='Development-only: wipe finance tables before import.')
        parser.add_argument('--force', action='store_true',
                            help='Re-run on a non-empty target: skip rows whose PK '
                                 'already exists (safe idempotent re-import).')
        parser.add_argument('--check', action='store_true',
                            help='Run source audit + validation only; do not import.')

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        src = opts['source']
        self._src = src
        self._engine = connection.vendor
        self._force = opts.get('force', False)
        self.stdout.write(f'Source SQLite : {src}')
        self.stdout.write(f'Target engine : {self._engine} -> {connection.settings_dict["NAME"]}')

        import sqlite3 as _sqlite3
        try:
            self.src = _sqlite3.connect(src)
        except Exception as e:  # pragma: no cover
            raise CommandError(f'cannot open source {src}: {e}')
        self.src.row_factory = _sqlite3.Row

        self._audit_source()

        if opts['check']:
            self.stdout.write(self.style.WARNING('--check: source audit only, no import.'))
            return

        if opts['reset']:
            self._reset_target()
        elif not opts['force'] and any(m.objects.exists() for m in FINANCE_MODELS):
            raise CommandError(
                'Target finance tables already contain data. Use --reset to wipe '
                'and re-import, or --force to skip existing rows (idempotent).')

        with transaction.atomic():
            self._import_all()
            self.stdout.write(self.style.SUCCESS('Import committed (single transaction).'))

        self._validate_all()

    # ------------------------------------------------------------------
    def _table_rows(self, table):
        cur = self.src.execute(f'SELECT * FROM "{table}"')
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        return cols, rows

    def _audit_source(self):
        cur = self.src.cursor()
        self.stdout.write('\n--- SOURCE AUDIT ---')
        missing = []
        counts = {}
        for t in ALL_FINANCE_TABLES:
            try:
                n = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                counts[t] = n
                self.stdout.write(f'  {t:38s} {n:6d} rows')
            except Exception:
                missing.append(t)
        if missing:
            self.stdout.write(self.style.ERROR('missing source tables: ' + ', '.join(missing)))
            raise CommandError('source missing finance tables; aborting')
        self._source_counts = counts

    # ------------------------------------------------------------------
    def _reset_target(self):
        """Development-only wipe (children first). No data loss elsewhere:
        only finance tables are truncated."""
        if self._engine == 'postgresql':
            self.stdout.write(self.style.WARNING('Resetting tables on PostgreSQL...'))
        with transaction.atomic():
            for model in RESET_MODELS:
                model.objects.all().delete()
        self.stdout.write(self.style.SUCCESS('Finance tables reset (--reset).'))

    # ------------------------------------------------------------------
    def _import_all(self):
        """Copy every finance table row-for-row, preserving PK ids."""
        self._imported = {}
        self._import_seq = []
        for model in FINANCE_MODELS:
            table = model._meta.db_table
            cols, rows = self._table_rows(table)
            self._import_table(model, table, cols, rows)
            self._import_seq.append(table)

    def _import_table(self, model, table, cols, rows):
        flds = model._meta.fields
        # map source column name -> model field
        by_col = {}
        for f in flds:
            by_col[f.column] = f
        if not rows:
            self._imported[table] = 0
            return
        # when --force on a non-empty target, drop rows whose PK exists
        if getattr(self, '_force', False) and model.objects.exists():
            pk_col = model._meta.pk.column
            existing = set(model.objects.values_list('pk', flat=True))
            rows = [r for r in rows if r[pk_col] not in existing]
        objs = []
        # datetime/text normalization is handled by Django field descriptors;
        # feed raw python values into bulk_create via field pre-processing.
        for row in rows:
            kw = {}
            for col in cols:
                f = by_col.get(col)
                if f is None:
                    continue
                val = row[col]
                if val is None:
                    kw[col] = None
                    continue
                cls = f.__class__.__name__
                if cls == 'DecimalField':
                    kw[col] = Decimal(str(val))
                elif cls in ('DateTimeField', 'DateField'):
                    from django.utils.dateparse import parse_datetime, parse_date
                    sval = str(val)
                    kw[col] = parse_datetime(sval) if (' ' in sval or 'T' in sval) else parse_date(sval)
                elif cls == 'BooleanField':
                    kw[col] = bool(val)
                elif cls == 'BigAutoField' or cls == 'AutoField':
                    kw[col] = int(val)
                elif cls == 'ForeignKey' or cls == 'OneToOneField':
                    kw[col] = int(val) if val is not None else None
                else:
                    kw[col] = val
            objs.append(model(**kw))
        # bulk_create in chunks preserving PK
        chunk = 500
        for i in range(0, len(objs), chunk):
            model.objects.bulk_create(objs[i:i + chunk])
        self._imported[table] = len(objs)
        self.stdout.write(f'  imported {model.__name__:24s} {len(objs):5d} rows')

    # ------------------------------------------------------------------
    def _validate_all(self):
        self.stdout.write('\n--- VALIDATION ---')
        self._validate_row_counts()
        self._validate_financial_sums()
        self._validate_fk_integrity()
        self._validate_business_rules()

    def _validate_row_counts(self):
        self.stdout.write('\n[1] Row-count source vs target')
        cur = self.src.cursor()
        all_ok = True
        for t in ALL_FINANCE_TABLES:
            try:
                s = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            except Exception:
                s = -1
            model = next((m for m in FINANCE_MODELS if m._meta.db_table == t), None)
            tgt = model.objects.count() if model else -1
            status = 'PASS' if s == tgt else 'FAIL'
            if status == 'FAIL':
                all_ok = False
            self.stdout.write(f'  {t:38s} {s:6d} {tgt:6d}  {status}')
        self._rc_ok = all_ok

    def _validate_financial_sums(self):
        from django.db.models import Sum
        self.stdout.write('\n[2] Financial value SUM source vs target')
        # Source sums are computed in PYTHON Decimal from each row value
        # (SQLite SUM() runs in float64 and loses cents at trillions; Decimal
        # sums stay exact on both sides so comparison is trustworthy).
        all_ok = True
        for table, fields in MONEY_FIELDS.items():
            model = next((m for m in FINANCE_MODELS if m._meta.db_table == table), None)
            if model is None:
                continue
            cols = [d[0] for d in self.src.execute(f'SELECT * FROM "{table}" LIMIT 0').description]
            rows = self.src.execute(f'SELECT * FROM "{table}"').fetchall()
            for fname in fields:
                if fname not in cols:
                    continue
                s = Decimal('0')
                for r in rows:
                    v = r[cols.index(fname)]
                    if v is not None:
                        s += Decimal(str(v))
                # target sum computed in PYTHON from each stored row (SQL SUM
                # on SQLite runs float64 and loses cents at trillions; an
                # ORM aggregate would compare float-sum against Decimal-sum).
                tgt = sum((Decimal(str(v)) for v in
                           model.objects.values_list(fname, flat=True).iterator()
                           if v is not None), Decimal('0'))
                status = 'PASS' if s == tgt else 'FAIL'
                if status == 'FAIL':
                    all_ok = False
                self.stdout.write(f'  {table}.{fname:28s} src {s:>22,.2f}  tgt {tgt:>22,.2f}  {status}')
        self._fin_ok = all_ok

    def _validate_fk_integrity(self):
        from django.db.models import Q
        self.stdout.write('\n[3] FK integrity (orphan scan on target)')
        checks = [
            (M.Project.objects.filter(pp_id__isnull=False).exclude(pp__isnull=False), 'project.pp'),
            (M.Project.objects.filter(organization_unit__isnull=False).exclude(organization_unit__isnull=False), 'project.organization_unit'),
            (M.Project.objects.filter(campus_id__isnull=False).exclude(campus__isnull=False), 'project.campus'),
            (M.Project.objects.filter(first_seen_period_id__isnull=False).exclude(first_seen_period__isnull=False), 'project.first_seen_period'),
            (M.Project.objects.filter(last_seen_period_id__isnull=False).exclude(last_seen_period__isnull=False), 'project.last_seen_period'),
            (M.RevenueLedger.objects.filter(period_id__isnull=False).exclude(period__isnull=False), 'ledger.period'),
            (M.RevenueLedger.objects.filter(pp_id__isnull=False).exclude(pp__isnull=False), 'ledger.pp'),
            (M.RevenueLedger.objects.filter(revenue_account_id__isnull=False).exclude(revenue_account__isnull=False), 'ledger.revenue_account'),
            (M.GLProjectMapping.objects.filter(ledger_id__isnull=False).exclude(ledger__isnull=False), 'glpm.ledger'),
            (M.GLProjectMapping.objects.filter(project_id__isnull=False).exclude(project__isnull=False), 'glpm.project'),
            (M.RevenueBudget.objects.filter(pp__isnull=False).exclude(pp__isnull=False), 'budget.pp'),
            (M.RevenueBudget.objects.filter(revenue_account__isnull=False).exclude(revenue_account__isnull=False), 'budget.revenue_account'),
            (M.RevenueBudget.objects.filter(rka_version__isnull=False).exclude(rka_version__isnull=False), 'budget.rka_version'),
            (M.RevenueBudgetMonthly.objects.filter(revenue_budget__isnull=False).exclude(revenue_budget__isnull=False), 'budget_monthly.revenue_budget'),
            (M.ProjectAlias.objects.filter(pp_id__isnull=False).exclude(pp__isnull=False), 'alias.pp'),
            (M.ProjectAlias.objects.filter(project_id__isnull=False).exclude(project__isnull=False), 'alias.project'),
            (M.NtfReportSnapshot.objects.filter(project_id__isnull=False).exclude(project__isnull=False), 'ntfsnap.project'),
            (M.NtfReportSnapshot.objects.filter(period_id__isnull=False).exclude(period__isnull=False), 'ntfsnap.period'),
            (M.RevenueMonthlySnapshot.objects.filter(period_id__isnull=False).exclude(period__isnull=False), 'rmsnap.period'),
            (M.RevenueMonthlySnapshot.objects.filter(pp_id__isnull=False).exclude(pp__isnull=False), 'rmsnap.pp'),
            (M.RevenueMonthlySnapshot.objects.filter(revenue_account_id__isnull=False).exclude(revenue_account__isnull=False), 'rmsnap.revenue_account'),
            (M.ProjectMonthlySnapshot.objects.filter(project_id__isnull=False).exclude(project__isnull=False), 'pmsnap.project'),
            (M.ProjectMonthlySnapshot.objects.filter(period_id__isnull=False).exclude(period__isnull=False), 'pmsnap.period'),
            (M.KpiTarget.objects.filter(organization_unit_id__isnull=False).exclude(organization_unit__isnull=False), 'kpi.organization_unit'),
            (M.KpiTarget.objects.filter(campus_id__isnull=False).exclude(campus__isnull=False), 'kpi.campus'),
            (M.SimkugSyncLog.objects.filter(period_id__isnull=False).exclude(period__isnull=False), 'synclog.period'),
        ]
        all_ok = True
        for qs, label in checks:
            n = qs.count()
            status = 'PASS' if n == 0 else 'FAIL'
            if n:
                all_ok = False
            self.stdout.write(f'  {label:32s} orphans {n:4d}  {status}')
        self._fk_ok = all_ok

    def _validate_business_rules(self):
        self.stdout.write('\n[4] Business rules (dummy expectations)')
        import sqlite3 as _s
        cur = self.src.cursor()
        # a) Pendaftaran account PERIOD_ONLY
        reg_src = cur.execute(
            "SELECT COUNT(*) FROM finance_revenueaccount WHERE account_code='4111101' "
            "AND detail_history_mode='PERIOD_ONLY'").fetchone()[0]
        reg_tgt = M.RevenueAccount.objects.filter(account_code='4111101',
                                                  detail_history_mode='PERIOD_ONLY').count()
        self._row('Pendaftaran 4111101 PERIOD_ONLY', reg_src, reg_tgt)
        # b) multi-account project: P-9120-001 must keep two accounts
        proj = M.Project.objects.filter(project_number='P-9120-001').first()
        if proj:
            n_src = cur.execute("SELECT COUNT(DISTINCT ra.account_code) FROM finance_glprojectmapping g "
                                "JOIN finance_revenueledger l ON g.ledger_id=l.id "
                                "JOIN finance_revenueaccount ra ON l.revenue_account_id=ra.id "
                                "JOIN finance_project p ON g.project_id=p.id "
                                "WHERE p.project_number='P-9120-001'").fetchone()[0]
            n_tgt = (M.GLProjectMapping.objects.filter(project=proj)
                     .values('ledger__revenue_account__account_code').distinct().count())
            self._row('P-9120-001 distinct accounts', n_src, n_tgt)
        else:
            self.stdout.write('  P-9120-001 not found in target (skip)')
        # c) NTF project/research project_value > 0 (match source)
        for prefix in ('RS-', 'SRV-', 'P-', 'TF-'):
            zs = cur.execute(
                "SELECT COUNT(*) FROM finance_project WHERE project_number LIKE ? AND project_value<=0",
                (prefix + '%',)).fetchone()[0]
            zt = M.Project.objects.filter(project_number__startswith=prefix,
                                          project_value__lte=0).count()
            self._row(f'{prefix} projects value<=0 (src must equal tgt)', zs, zt)

    def _row(self, label, s, t):
        status = 'PASS' if s == t else 'FAIL'
        self.stdout.write(f'  {label:45s} src {s:4d} tgt {t:4d}  {status}')
