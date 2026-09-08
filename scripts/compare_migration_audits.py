"""Compare audit files without printing credentials, rows or financial totals."""
import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path


def compare(source, target):
    failures = []
    if source.get('vendor') != 'mysql' or target.get('vendor') != 'postgresql':
        failures.append('Expected MySQL source and PostgreSQL target.')
    for label, report in [('source', source), ('target', target)]:
        if report.get('format_version') != 1 or not report.get('read_only'):
            failures.append(f'{label}: invalid audit format.')
        if report.get('issues') or report.get('status') != 'PASS':
            failures.append(f'{label}: audit findings require review.')
    if source.get('applied_migrations') != target.get('applied_migrations'):
        failures.append('Migration histories differ.')
    source_tables, target_tables = source.get('tables', {}), target.get('tables', {})
    if not source_tables or not target_tables:
        failures.append('Audit contains no tables.')
    rows = []
    for table in sorted(source_tables.keys() | target_tables.keys()):
        before = len(failures)
        a, b = source_tables.get(table), target_tables.get(table)
        if a is None or b is None:
            failures.append(f'{table}: missing table.')
            rows.append((table, a and a.get('count'), b and b.get('count'), 'FAIL'))
            continue
        if a['count'] != b['count']:
            failures.append(f'{table}: row count differs.')
        # Schema recorder timestamps are engine-specific; applied migration names
        # are checked above. All actual business/auth/session rows are hashed.
        if table != 'django_migrations':
            if not a.get('row_sha256') or a.get('row_sha256') != b.get('row_sha256'):
                failures.append(f'{table}: row values differ or hash missing.')
            if a.get('hash_fields') != b.get('hash_fields'):
                failures.append(f'{table}: hash field order differs.')
        for field in a.get('decimal_totals', {}).keys() | b.get('decimal_totals', {}).keys():
            sa = a.get('decimal_totals', {})
            sb = b.get('decimal_totals', {})
            if field not in sa or field not in sb:
                failures.append(f'{table}.{field}: financial control missing.')
            elif sa[field] is None or sb[field] is None:
                if sa[field] != sb[field]:
                    failures.append(f'{table}.{field}: NULL aggregate differs.')
            elif Decimal(sa[field]) != Decimal(sb[field]):
                failures.append(f'{table}.{field}: financial difference is nonzero.')
        for label, entry in [('source', a), ('target', b)]:
            if any(entry.get('orphans', {}).values()):
                failures.append(f'{table}: {label} foreign-key failure.')
        rows.append((table, a['count'], b['count'], 'PASS' if len(failures) == before else 'FAIL'))
    return rows, failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    args = parser.parse_args()
    try:
        rows, failures = compare(json.loads(args.source.read_text(encoding='utf-8')),
                                 json.loads(args.target.read_text(encoding='utf-8')))
    except Exception as exc:
        print(f'FAIL: audit comparison could not run ({type(exc).__name__}).')
        return 1
    print(f"{'TABLE':45} {'MYSQL':>10} {'POSTGRES':>10} STATUS")
    for table, source, target, status in rows:
        print(f'{table:45} {str(source):>10} {str(target):>10} {status}')
    for failure in failures:
        print('FAIL:', failure)
    print('Reconciliation:', 'FAIL' if failures else 'PASS')
    return int(bool(failures))


if __name__ == '__main__':
    sys.exit(main())
