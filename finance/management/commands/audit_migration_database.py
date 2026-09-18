"""Read-only migration baseline; does not create schema, data or backups."""
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, models, transaction
from django.db.migrations.loader import MigrationLoader


def canonical(value):
    """Lossless, cross-engine values for hashing; never round a financial value."""
    if isinstance(value, Decimal):
        # Do not use Decimal.normalize(): it can round to context precision.
        text = format(value, 'f')
        text = text.rstrip('0').rstrip('.') if '.' in text else text
        return {'decimal': '0' if value == 0 else text}
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return {'datetime': value.isoformat(timespec='microseconds')}
    if isinstance(value, date):
        return {'date': value.isoformat()}
    if isinstance(value, bytes):
        return {'bytes': value.hex()}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if isinstance(value, dict):
        return {str(k): canonical(v) for k, v in value.items()}
    return value


@contextmanager
def readonly_snapshot(connection):
    """Server-enforced read-only transaction. Always roll back on completion."""
    if connection.in_atomic_block:
        raise CommandError('Audit must run outside an existing transaction.')
    if connection.vendor not in {'mysql', 'postgresql', 'sqlite'}:
        raise CommandError('Unsupported audit database vendor.')
    connection.ensure_connection()
    if connection.vendor == 'mysql':
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
    if connection.vendor == 'sqlite':
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA query_only = ON')
    try:
        with transaction.atomic(using=connection.alias):
            with connection.cursor() as cursor:
                if connection.vendor == 'mysql':
                    # No data query occurs before this consistent snapshot.
                    cursor.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
                elif connection.vendor == 'postgresql':
                    cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            try:
                yield
            finally:
                transaction.set_rollback(True, using=connection.alias)
    finally:
        if connection.vendor == 'sqlite':
            with connection.cursor() as cursor:
                cursor.execute('PRAGMA query_only = OFF')


def business_findings(alias):
    from finance.models import GLProjectMapping, Project, RevenueBudget

    issues = []
    project_accounts = {}
    bad_pp = 0
    for row in GLProjectMapping.objects.using(alias).filter(project__isnull=False).values(
        'project_id', 'project__pp_id', 'ledger__pp_id',
        'ledger__revenue_account__account_code', 'ledger__account_code_raw',
    ).iterator(chunk_size=1000):
        account = row['ledger__revenue_account__account_code'] or row['ledger__account_code_raw']
        project_accounts.setdefault(row['project_id'], set()).add(account or '<unmapped>')
        if row['project__pp_id'] != row['ledger__pp_id']:
            bad_pp += 1
    multiple = sum(len(accounts) > 1 for accounts in project_accounts.values())
    if multiple:
        issues.append({'code': 'PROJECT_ACCOUNT_MISMATCH', 'count': multiple})
    if bad_pp:
        issues.append({'code': 'PROJECT_PP_MISMATCH', 'count': bad_pp})
    missing_pp = Project.objects.using(alias).filter(pp__isnull=True).count()
    if missing_pp:
        issues.append({'code': 'PROJECT_PP_MISSING', 'count': missing_pp})
    phasing = RevenueBudget.objects.using(alias).annotate(
        phased=models.Sum('monthly_rows__budget_amount')
    ).values_list('annual_budget', 'phased')
    mismatches = sum(annual != (phased if phased is not None else Decimal(0))
                     for annual, phased in phasing.iterator(chunk_size=1000))
    if mismatches:
        issues.append({'code': 'RKA_PHASING_MISMATCH', 'count': mismatches})
    # PostgreSQL enforces this partial unique constraint; MySQL does not.
    from finance.models import RevenueLedger
    duplicates = (RevenueLedger.objects.using(alias)
                  .filter(source_transaction_id__gt='')
                  .values('source_transaction_id', 'source_line_id')
                  .annotate(n=models.Count('pk')).filter(n__gt=1).count())
    if duplicates:
        issues.append({'code': 'DUPLICATE_GL_SOURCE_ID', 'count': duplicates})
    return issues


def collect_audit(connection):
    alias = connection.alias
    quote = connection.ops.quote_name
    model_map = {
        m._meta.db_table: m for m in apps.get_models(include_auto_created=True)
        if m._meta.managed and not m._meta.proxy
    }
    expected = {table for table in model_map if table.startswith('finance_')}
    report = {'format_version': 1, 'vendor': connection.vendor,
              'read_only': True, 'tables': {}, 'issues': []}
    with connection.cursor() as cursor:
        table_names = connection.introspection.table_names(cursor)
        selected = sorted(t for t in table_names if t.startswith(('finance_', 'auth_', 'django_')))
        for missing in sorted(expected - set(selected)):
            report['issues'].append({'code': 'MISSING_FINANCE_TABLE', 'table': missing})
        for table in selected:
            cursor.execute(f'SELECT COUNT(*) FROM {quote(table)}')
            count = cursor.fetchone()[0]
            description = connection.introspection.get_table_description(cursor, table)
            constraints = connection.introspection.get_constraints(cursor, table)
            columns = []
            for col in description:
                try:
                    field_type = connection.introspection.get_field_type(col.type_code, col)
                except KeyError:
                    field_type = str(col.type_code)
                columns.append({'name': col.name, 'type': field_type,
                                'nullable': col.null_ok, 'precision': col.precision,
                                'scale': col.scale})
            entry = {'count': count, 'columns': columns, 'constraints': constraints,
                     'decimal_totals': {}, 'orphans': {}}
            report['tables'][table] = entry
            if connection.vendor == 'mysql':
                cursor.execute('SELECT ENGINE FROM information_schema.TABLES '
                               'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s', [table])
                engine = cursor.fetchone()[0]
                entry['storage_engine'] = engine
                if engine != 'InnoDB':
                    report['issues'].append({'code': 'NON_TRANSACTIONAL_SOURCE_TABLE', 'table': table})
            model = model_map.get(table)
            if model is None:
                if table != 'django_migrations':
                    report['issues'].append({'code': 'UNMODELLED_TABLE', 'table': table})
                continue
            fields = model._meta.local_concrete_fields
            if {f.column for f in fields} != {col.name for col in description}:
                report['issues'].append({'code': 'SCHEMA_COLUMN_MISMATCH', 'table': table})
                continue
            column_types = {col['name']: col for col in columns}
            for field in fields:
                if isinstance(field, models.DecimalField):
                    col = column_types[field.column]
                    if col['type'] != 'DecimalField':
                        report['issues'].append({'code': 'NON_DECIMAL_FINANCIAL_COLUMN',
                                                 'table': table, 'field': field.name})
                    if connection.vendor != 'sqlite' and (
                        col['precision'] != field.max_digits or col['scale'] != field.decimal_places
                    ):
                        report['issues'].append({'code': 'DECIMAL_SCHEMA_MISMATCH',
                                                 'table': table, 'field': field.name})
                    cursor.execute(f'SELECT SUM({quote(field.column)}) FROM {quote(table)}')
                    value = cursor.fetchone()[0]
                    if isinstance(value, float):
                        report['issues'].append({'code': 'FLOAT_AGGREGATE_NOT_EXACT',
                                                 'table': table, 'field': field.name})
                    entry['decimal_totals'][field.name] = str(value) if value is not None else None
                if field.is_relation and field.many_to_one:
                    parent_table = field.related_model._meta.db_table
                    parent_col = field.target_field.column
                    cursor.execute(
                        f'SELECT COUNT(*) FROM {quote(table)} child LEFT JOIN '
                        f'{quote(parent_table)} parent ON child.{quote(field.column)} = '
                        f'parent.{quote(parent_col)} WHERE child.{quote(field.column)} IS NOT NULL '
                        f'AND parent.{quote(parent_col)} IS NULL'
                    )
                    orphan_count = cursor.fetchone()[0]
                    entry['orphans'][field.name] = orphan_count
                    if orphan_count:
                        report['issues'].append({'code': 'ORPHAN_FK', 'table': table,
                                                 'field': field.name, 'count': orphan_count})
            digest = hashlib.sha256()
            # Explicit field + PK order makes comparisons independent of schema order.
            field_names = [f.attname for f in fields]
            qs = model._base_manager.using(alias).order_by(model._meta.pk.attname)
            for row in qs.values_list(*field_names).iterator(chunk_size=1000):
                data = json.dumps(canonical(row), sort_keys=True, ensure_ascii=False,
                                  separators=(',', ':'), allow_nan=False)
                digest.update(data.encode('utf-8') + b'\n')
            entry['row_sha256'] = digest.hexdigest()
            entry['hash_fields'] = field_names
    loader = MigrationLoader(connection)
    report['applied_migrations'] = sorted([list(key) for key in loader.applied_migrations])
    report['unapplied_migrations'] = sorted([list(key) for key in loader.disk_migrations
                                           if key not in loader.applied_migrations])
    if report['unapplied_migrations']:
        report['issues'].append({'code': 'UNAPPLIED_MIGRATIONS'})
    if not report['issues']:
        report['issues'].extend(business_findings(alias))
    report['status'] = 'PASS' if not report['issues'] else 'WARNING'
    return report


class Command(BaseCommand):
    help = 'Read-only schema, counts, exact financial totals, row hashes and FK audit.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--database', default='source')
        parser.add_argument('--expect-vendor', choices=['mysql', 'postgresql'], required=True)
        parser.add_argument('--output', type=Path, required=True)

    def handle(self, *args, **options):
        stage = 'configuration'
        try:
            connection = connections[options['database']]
            if connection.vendor != options['expect_vendor']:
                raise CommandError('Database vendor differs from --expect-vendor; stopped.')
            if options['output'].exists():
                raise CommandError('Audit output already exists; choose a new filename.')
            stage = 'read-only database audit'
            with readonly_snapshot(connection):
                report = collect_audit(connection)
            stage = 'writing audit report'
            options['output'].parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(options['output'], os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(report, stream, indent=2, default=str)
                stream.write('\n')
        except CommandError:
            raise
        except Exception as exc:
            # Driver errors can contain usernames, hostnames, SQL or credentials.
            raise CommandError(f'Audit failed during {stage} ({type(exc).__name__}); '
                               'check local configuration and access. No source writes performed.') from None
        self.stdout.write(f"Vendor: {report['vendor']}; read-only: True; status: {report['status']}")
        self.stdout.write(f"Tables audited: {len(report['tables'])}; issues: {len(report['issues'])}")
        if report['issues']:
            raise CommandError('Audit completed with findings. Review the saved report before migration.')
