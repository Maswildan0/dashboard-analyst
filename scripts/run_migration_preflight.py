"""Run local read-only source/Neon probes. Never migrate, seed, import or deploy."""
import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-env-file', type=Path)
    parser.add_argument('--target-env-file', type=Path)
    parser.add_argument('--output-dir', type=Path, default=Path('.migration-artifacts'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.chdir(root)
    try:
        from dotenv import dotenv_values
        if args.source_env_file:
            if not args.source_env_file.is_file():
                raise ValueError('Source environment file does not exist.')
            source = dotenv_values(args.source_env_file, interpolate=False)
            if source.get('DB_ENGINE') != 'mysql' and not source.get('SOURCE_DB_NAME'):
                raise ValueError('Source file must specify DB_ENGINE=mysql or SOURCE_DB_NAME.')
            # A selected file has priority only within this subprocess. It never
            # rewrites the original file or the parent PowerShell environment.
            for name in ('NAME', 'HOST', 'PORT', 'USER', 'PASSWORD'):
                value = source.get('SOURCE_DB_' + name, source.get('DB_' + name))
                if value is not None:
                    os.environ['SOURCE_DB_' + name] = value
        if args.target_env_file:
            if not args.target_env_file.is_file():
                raise ValueError('Target environment file does not exist.')
            target = dotenv_values(args.target_env_file, interpolate=False)
            if not target.get('DATABASE_URL'):
                raise ValueError('Target file does not contain DATABASE_URL.')
            # Avoid accidentally retaining a production direct URL when the
            # selected preview file supplies only its pooled URL.
            for name in ('DATABASE_URL', 'DATABASE_URL_UNPOOLED'):
                os.environ.pop(name, None)
                if target.get(name):
                    os.environ[name] = target[name]
        if not os.environ.get('SOURCE_DB_NAME'):
            raise ValueError('Set SOURCE_DB_NAME locally or select the existing MySQL .env file.')
        os.environ.pop('DJANGO_ENV_FILE', None)
        os.environ['DJANGO_SETTINGS_MODULE'] = 'dashboard.migration_settings'
        import django
        django.setup()
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from datetime import datetime, timezone
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        output = args.output_dir / f'source-audit-{stamp}.json'
        source_ok = True
        try:
            call_command('audit_migration_database', database='source', expect_vendor='mysql', output=output)
            print('Source audit = PASS')
        except CommandError as exc:
            source_ok = False
            print('Source audit = WARNING/FAIL; review the audit report if created, otherwise local source access.')
            print(str(exc))  # These audit commands sanitize driver exceptions.
        if output.exists():
            print('Source audit file:', output)
        target_ok = False
        print('DATABASE_URL exists =', bool(os.environ.get('DATABASE_URL')))
        if os.environ.get('DATABASE_URL'):
            try:
                call_command('verify_database_connection')
                target_ok = True
            except CommandError as exc:
                print('Target connection = FAIL; check Vercel Preview configuration and network access.')
                print(str(exc))
        else:
            print('Target connection = NOT CHECKED; no DATABASE_URL in this process.')
        print('No schema migration, backup, import or deployment performed.')
        return 0 if source_ok and target_ok else 1
    except Exception as exc:
        # Never print raw exception text: dotenv paths and driver errors may
        # contain sensitive values. Configuration-specific instructions are in
        # docs/neon-migration.md.
        print(f'Preflight could not start ({type(exc).__name__}). Check local prerequisites in docs/neon-migration.md.')
        return 1


if __name__ == '__main__':
    sys.exit(main())
