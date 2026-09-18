from django.core.management.base import BaseCommand, CommandError
from django.db import connections


class Command(BaseCommand):
    help = 'Verify PostgreSQL connectivity and actual TLS without displaying credentials.'
    requires_system_checks = []

    def handle(self, *args, **options):
        connection = connections['default']
        if connection.vendor != 'postgresql':
            raise CommandError('Expected PostgreSQL. No connection attempted.')
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                if cursor.fetchone() != (1,):
                    raise CommandError('Database probe failed.')
                cursor.execute('SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()')
                row = cursor.fetchone()
                if row != (True,):
                    raise CommandError('PostgreSQL connection is not using TLS.')
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f'PostgreSQL connection failed ({type(exc).__name__}). '
                               'Check local environment and access; credentials are not displayed.') from None
        finally:
            connection.close()
        self.stdout.write('connection.vendor = postgresql\nDatabase connection = OK\nSSL = True')
