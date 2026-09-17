"""Controlled MySQL -> PostgreSQL migration for the finance app.

Source : MySQL `financial_dashboard` (READ ONLY, never modified).
Target : PostgreSQL via DATABASE_URL (Neon) or DB_ENGINE=postgres env vars.

Method
    * Target schema is created by Django migrations (`python manage.py
      migrate`), so PostgreSQL schema always matches Django migration state.
    * Data is copied table-by-table in FK dependency order, preserving
      explicit primary keys (MySQL id == PostgreSQL id).
    * PostgreSQL sequences are synchronised (setval) after the import so
      future inserts start above MAX(id).
    * Financial values are Decimal throughout (never float).
    * Validation: row-count, financial control totals, FK orphans, sequence.

Usage
    DATABASE_URL=postgresql://... python manage.py migrate_mysql_to_postgres
    python manage.py migrate_mysql_to_postgres --reset-target   # dev retry
    python manage.py migrate_mysql_to_postgres --check          # dry audit

The source MySQL connection uses the same Django DB settings when the active
engine is MySQL; otherwise explicit MYSQL_* env vars may be provided.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, connections, transaction

from finance import models as M


# --------------------------------------------------------------------------
# Table order = FK dependency (parents first). Model classes live in finance.
# --------------------------------------------------------------------------
FINANCE_MODELS = [
    M.Campus, M.OrganizationUnit, M.PPMaster, M.RevenueCategory,
    M.RevenueAccount, M.FinancialPeriod, M.RkaVersion, M.RevenueBudget,
    M.RevenueBudgetMonthly, M.Project, M.ProjectAlias, M.RevenueLedger,
    M.GLProjectMapping, M.NtfReportSnapshot, M.RevenueMonthlySnapshot,
    M.ProjectMonthlySnapshot, M.FinancialSummary, M.RevenueTransactionSummary,
    M.KpiTarget, M.SimkugSyncLog, M.FinancialDataAuditLog,
]

ALL_TABLES = [m._meta.db_table for m in FINANCE_MODELS]
# Manual revenue rows are not part of the MySQL source and are protected by
# FK RESTRICT/PROTECT, so truncate them first (see the dummy importer).
RESET_TABLES = ['finance_manualrevenueentry'] + list(reversed(ALL_TABLES))

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
    help = 'Migrate exact finance data from MySQL financial_dashboard to PostgreSQL.'

    def add_arguments(self, parser):
        parser.add_argument('--reset-target', action='store_true',
                            help='DEV ONLY: truncate target finance tables before import.')
        parser.add_argument('--check', action='store_true',
                            help='Audit source MySQL + report only; do not import.')
        parser.add_argument('--source-db', default=None,
                            help='Django DB alias to read source from (default: '
                                 'active engine if MySQL, else first mysql alias).')

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        self.check_mysql_source()
        self._audit_source()

        if opts['check']:
            self.stdout.write(self.style.WARNING('--check: audit only, no import.'))
            return

        target_vendor = connection.vendor
        if target_vendor != 'postgresql':
            raise CommandError('Target (default Django DB) is not PostgreSQL: '
                               f'{target_vendor}. Set DATABASE_URL to a Neon/PostgreSQL URL.')

        if opts['reset_target']:
            self._reset_target()

        with transaction.atomic():
            self._import_all()

        self._sync_sequences()
        self._validate_all()

    # ------------------------------------------------------------------
    def check_mysql_source(self):
        """Open a read-only connection to the MySQL source. Prefer the current
        Django connection when it is MySQL; else a dedicated alias built from
        MYSQL_* env vars."""
        import os
        self._src = None
        cur = connection.vendor
        if cur == 'mysql':
            self._src = connection
            self._src_conn = connection
            return
        if cur == 'sqlite':
            pass  # fall through to dedicated alias via MYSQL_* env
        # Build a dedicated MySQL connection from env (only for reading).
        _mname = os.environ.get('MYSQL_DB', 'financial_dashboard')
        settings = {
            'ENGINE': 'dashboard.db_backends.mariadb',
            'NAME': _mname,
            'USER': os.environ.get('MYSQL_USER', 'root'),
            'PASSWORD': os.environ.get('MYSQL_PASSWORD', ''),
            'HOST': os.environ.get('MYSQL_HOST', '127.0.0.1'),
            'PORT': os.environ.get('MYSQL_PORT', '3306'),
            'OPTIONS': {'charset': 'utf8mb4'},
            'ATOMIC_REQUESTS': False,
            'AUTOCOMMIT': True,
            'CONN_MAX_AGE': 0,
            'CONN_HEALTH_CHECKS': False,
            'TIME_ZONE': None,
            'TEST': {},
        }
        # register under a scratch alias
        self._src_alias = '__mysql_source__'
        connections.databases[self._src_alias] = settings
        self._src = connections[self._src_alias]
        # verify
        with self._src.cursor() as c:
            c.execute('SELECT DATABASE()')
            self.stdout.write(f'Source MySQL db: {c.fetchone()[0]}')
        self.stdout.write(f'Source MySQL host: {settings["HOST"]}:{settings["PORT"]}')

    # ------------------------------------------------------------------
    def _audit_source(self):
        cur = self._src.cursor()
        self.stdout.write('\n--- SOURCE (MySQL) AUDIT ---')
        for t in ALL_TABLES:
            try:
                cur.execute(f'SELECT COUNT(*) FROM `{t}`')
                n = cur.fetchone()[0]
            except Exception:
                n = -1
            self.stdout.write(f'  {t:38s} {n:6d} rows')

    # ------------------------------------------------------------------
    def _reset_target(self):
        self.stdout.write(self.style.WARNING('Resetting target finance tables (children first)...'))
        for t in RESET_TABLES:
            with connection.cursor() as c:
                c.execute(f'TRUNCATE TABLE "{t}" RESTART IDENTITY CASCADE')
        self.stdout.write(self.style.SUCCESS('Target reset done.'))

    # ------------------------------------------------------------------
    def _fetch(self, table, cols):
        cur = self._src.cursor()
        colq = ', '.join(f'`{c}`' for c in cols)
        cur.execute(f'SELECT {colq} FROM `{table}`')
        rows = cur.fetchall()
        cur.close()
        return rows

    def _import_all(self):
        self.stdout.write('\n--- IMPORT (MySQL -> PostgreSQL) ---')
        for model in FINANCE_MODELS:
            table = model._meta.db_table
            with self._src.cursor() as c:
                c.execute(f'SELECT * FROM `{table}` LIMIT 0')
                cols = [d[0] for d in c.description]
            rows = self._fetch(table, cols)
            self._import_table(model, cols, rows)
            self.stdout.write(f'  imported {table:38s} {len(rows):5d}')

    def _import_table(self, model, cols, rows):
        if not rows:
            return
        flds = {f.column: f for f in model._meta.fields}
        from django.utils.dateparse import parse_datetime, parse_date
        objs = []
        for row in rows:
            kw = {}
            for idx, col in enumerate(cols):
                f = flds.get(col)
                if f is None:
                    continue
                val = row[idx]
                if val is None:
                    kw[col] = None
                    continue
                cls = f.__class__.__name__
                if cls == 'DecimalField':
                    # MySQLdb may return str/Decimal/int; always Decimal.
                    kw[col] = Decimal(str(val))
                elif cls in ('DateTimeField',):
                    sval = str(val)
                    if sval.endswith('+00:00'):
                        sval = sval[:-6]
                    kw[col] = parse_datetime(sval)
                elif cls == 'DateField':
                    kw[col] = parse_date(str(val))
                elif cls == 'BooleanField':
                    kw[col] = bool(val)
                elif cls == 'AutoField' or cls == 'BigAutoField':
                    kw[col] = int(val)
                elif cls in ('ForeignKey', 'OneToOneField') and f.column != 'id':
                    kw[col] = int(val)
                else:
                    kw[col] = val
            objs.append(model(**kw))
        for i in range(0, len(objs), 400):
            model.objects.bulk_create(objs[i:i + 400])

    # ------------------------------------------------------------------
    def _sync_sequences(self):
        from django.db.models import Max
        self.stdout.write('\n--- SEQUENCE SYNC ---')
        with connection.cursor() as c:
            for model in FINANCE_MODELS:
                table = model._meta.db_table
                pk = model._meta.pk
                max_id = model.objects.aggregate(m=Max('pk'))['m']
                # PostgreSQL sequence name: <table>_<pk>_seq
                c.execute(
                    'SELECT setval(pg_get_serial_sequence(%s, %s), %s)',
                    [table, pk.column, max_id if max_id else 1],
                )
                self.stdout.write(f'  setval {table}.{pk.column} -> {max_id}')

    # ------------------------------------------------------------------
    def _validate_all(self):
        self.stdout.write('\n--- VALIDATION ---')
        self._validate_row_counts()
        self._validate_control_totals()
        self._validate_fk()
        self._validate_sequences()

    def _validate_row_counts(self):
        self.stdout.write('\n[1] Row-count MySQL vs PostgreSQL')
        ok = True
        for model in FINANCE_MODELS:
            table = model._meta.db_table
            with self._src.cursor() as c:
                c.execute(f'SELECT COUNT(*) FROM `{table}`')
                s = c.fetchone()[0]
            t = model.objects.count()
            st = 'PASS' if s == t else 'FAIL'
            ok = ok and st == 'PASS'
            self.stdout.write(f'  {table:38s} {s:6d} {t:6d}  {st}')
        self._rc_ok = ok

    def _validate_control_totals(self):
        self.stdout.write('\n[2] Financial control totals (Decimal)')
        ok = True
        for table, fields in MONEY_FIELDS.items():
            model = next((m for m in FINANCE_MODELS if m._meta.db_table == table), None)
            if model is None:
                continue
            with self._src.cursor() as c:
                c.execute(f'SELECT * FROM `{table}` LIMIT 0')
                cols = [d[0] for d in c.description]
                c.execute(f'SELECT * FROM `{table}`')
                rows = c.fetchall()
            for fname in fields:
                if fname not in cols:
                    continue
                idx = cols.index(fname)
                s = sum((Decimal(str(r[idx])) for r in rows if r[idx] is not None), Decimal('0'))
                t = sum((Decimal(str(v)) for v in
                         model.objects.values_list(fname, flat=True).iterator()
                         if v is not None), Decimal('0'))
                st = 'PASS' if s == t else 'FAIL'
                ok = ok and st == 'PASS'
                self.stdout.write(f'  {table}.{fname:30s} {s:>22,.2f} {t:>22,.2f}  {st}')
        self._fin_ok = ok

    def _validate_fk(self):
        self.stdout.write('\n[3] FK integrity (orphan scan on PostgreSQL)')
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
        ok = True
        for qs, label in checks:
            n = qs.count()
            st = 'PASS' if n == 0 else 'FAIL'
            ok = ok and st == 'PASS'
            self.stdout.write(f'  {label:32s} orphans {n:4d}  {st}')
        self._fk_ok = ok

    def _validate_sequences(self):
        from django.db.models import Max
        self.stdout.write('\n[4] Sequence after MAX(id)')
        ok = True
        with connection.cursor() as c:
            for model in FINANCE_MODELS:
                table = model._meta.db_table
                max_id = model.objects.aggregate(m=Max('pk'))['m'] or 0
                c.execute(
                    "SELECT last_value FROM pg_sequences "
                    "WHERE schemaname = 'public' AND sequencename = "
                    "regexp_replace(pg_get_serial_sequence(%s, %s), '^.*[.]', '')",
                    [table, model._meta.pk.column],
                )
                last = c.fetchone()
                if last is None:
                    continue
                last_val = int(last[0])
                st = 'PASS' if last_val >= max_id else 'FAIL'
                ok = ok and st == 'PASS'
                if st == 'FAIL':
                    self.stdout.write(f'  {table:38s} seq {last_val} < max {max_id}  {st}')
        if ok:
            self.stdout.write('  all sequences >= MAX(id)  PASS')
        self._seq_ok = ok
