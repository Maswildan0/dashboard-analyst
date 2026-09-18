import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, DatabaseError
from django.test import SimpleTestCase, TransactionTestCase

from dashboard.database_config import database_config, postgres_url_config
from finance.management.commands.audit_migration_database import (
    canonical, collect_audit, readonly_snapshot,
)
from finance.models import Campus
from scripts.compare_migration_audits import compare


class ConfigurationTests(SimpleTestCase):
    def test_neon_url_has_priority_and_pooler_safe_options(self):
        config = database_config({'DATABASE_URL': 'postgresql://user:pass@host/db',
                                  'DB_ENGINE': 'mysql'}, Path('/tmp'))
        self.assertEqual(config['ENGINE'], 'django.db.backends.postgresql')
        self.assertEqual(config['OPTIONS']['sslmode'], 'require')
        self.assertEqual(config['CONN_MAX_AGE'], 0)
        self.assertTrue(config['DISABLE_SERVER_SIDE_CURSORS'])

    def test_bad_urls_fail_without_revealing_credentials(self):
        for url in ['mysql://person:private-password@host/db',
                    'postgresql://person:private-password@host/',
                    'postgresql://person:private-password@[bad/db']:
            with self.subTest(url=url):
                with self.assertRaises(ImproperlyConfigured) as error:
                    postgres_url_config(url)
                self.assertNotIn('private-password', str(error.exception))

    def test_ssl_cannot_be_disabled_by_url(self):
        with self.assertRaises(ImproperlyConfigured):
            postgres_url_config('postgresql://user:pass@host/db?sslmode=disable')
        self.assertEqual(postgres_url_config(
            'postgresql://user:pass@host/db?sslmode=verify-full'
        )['OPTIONS']['sslmode'], 'verify-full')

    def test_mysql_fallback_preserves_existing_configuration(self):
        config = database_config({'DB_ENGINE': 'mysql', 'DB_NAME': 'source',
                                  'DB_USER': 'reader', 'DB_HOST': 'source-host'}, Path('/tmp'))
        self.assertEqual(config['ENGINE'], 'dashboard.db_backends.mariadb')
        self.assertEqual(config['NAME'], 'source')
        self.assertEqual(config['USER'], 'reader')

    def test_vercel_never_falls_back_to_sqlite(self):
        with self.assertRaises(ImproperlyConfigured):
            database_config({'VERCEL': '1'}, Path('/tmp'))
        self.assertEqual(database_config({}, Path('/tmp'))['ENGINE'], 'django.db.backends.sqlite3')

    def test_django_startup_does_not_query_or_create_a_database(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as folder:
            settings_file = Path(folder) / 'startup_settings.py'
            databases = {'default': {'ENGINE': 'django.db.backends.sqlite3',
                         'NAME': str(Path(folder) / 'must-not-exist.sqlite3')}}
            settings_file.write_text(
                'from dashboard.settings import *\n'
                'DATABASES = ' + repr(databases) + '\n',
                encoding='utf-8',
            )
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(('DB_', 'DATABASE_', 'DJANGO_', 'VERCEL'))}
            env.update({'PYTHONPATH': folder + os.pathsep + str(root),
                        'DJANGO_SETTINGS_MODULE': 'startup_settings'})
            result = subprocess.run([sys.executable, '-c', 'import django; django.setup()'],
                                    env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((Path(folder) / 'must-not-exist.sqlite3').exists())

    def test_connection_probe_refuses_sqlite(self):
        with self.assertRaisesMessage(CommandError, 'Expected PostgreSQL'):
            call_command('verify_database_connection')


class BaselineTests(TransactionTestCase):
    def test_readonly_transaction_blocks_writes_and_leaves_rows_intact(self):
        Campus.objects.create(code='AUDIT', name='Audit transaction fixture')
        with readonly_snapshot(connection):
            self.assertEqual(Campus.objects.count(), 1)
            with self.assertRaises(DatabaseError):
                Campus.objects.create(code='BLOCKED', name='Must not be stored')
        self.assertEqual(list(Campus.objects.values_list('code', flat=True)), ['AUDIT'])

    def test_audit_is_readonly_and_hash_covers_row_changes(self):
        campus = Campus.objects.create(code='AUDIT', name='Initial value')
        with readonly_snapshot(connection):
            first = collect_audit(connection)
        self.assertEqual(first['tables']['finance_campus']['count'], 1)
        self.assertEqual(first['tables']['finance_campus']['orphans'], {})
        campus.name = 'Changed value'
        campus.save(update_fields=['name'])
        with readonly_snapshot(connection):
            second = collect_audit(connection)
        self.assertNotEqual(first['tables']['finance_campus']['row_sha256'],
                            second['tables']['finance_campus']['row_sha256'])


class ReconciliationTests(SimpleTestCase):
    def baseline(self, vendor):
        return {'format_version': 1, 'vendor': vendor, 'read_only': True, 'status': 'PASS',
                'issues': [], 'applied_migrations': [['finance', '0001_initial']],
                'tables': {'finance_project': {'count': 1, 'row_sha256': 'same',
                           'hash_fields': ['id', 'project_value'], 'orphans': {'pp': 0},
                           'decimal_totals': {'project_value': '123456789012345678.91'}}}}

    def test_exact_match_passes_and_one_cent_difference_fails(self):
        source, target = self.baseline('mysql'), self.baseline('postgresql')
        self.assertEqual(compare(source, target)[1], [])
        target['tables']['finance_project']['decimal_totals']['project_value'] = '123456789012345678.92'
        self.assertTrue(compare(source, target)[1])

    def test_missing_hash_table_or_orphan_fails(self):
        for mutation in ['hash', 'table', 'orphan']:
            source, target = self.baseline('mysql'), self.baseline('postgresql')
            if mutation == 'hash':
                target['tables']['finance_project'].pop('row_sha256')
            elif mutation == 'table':
                target['tables'] = {}
            else:
                target['tables']['finance_project']['orphans']['pp'] = 1
            self.assertTrue(compare(source, target)[1])

    def test_hash_encoding_preserves_microseconds_and_large_decimals(self):
        value = Decimal('123456789012345678901234567890.12')
        with localcontext() as ctx:
            ctx.prec = 8
            self.assertEqual(canonical(value), {'decimal': '123456789012345678901234567890.12'})
        self.assertNotEqual(canonical(datetime(2026, 8, 1, microsecond=123456, tzinfo=timezone.utc)),
                            canonical(datetime(2026, 8, 1, microsecond=123457, tzinfo=timezone.utc)))
