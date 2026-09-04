"""Django backend shim: MariaDB/MySQL via the stock `mysql` backend.

XAMPP ships MariaDB 10.4.32.  Two Django 6.x assumptions break on it:

1. `check_database_version_supported()` (django/db/backends/base) refuses any
   MariaDB older than 10.11.  This XAMPP server is fine for the dummy
   dashboard, so the guard is relaxed for MariaDB >= 10.4.
2. `can_return_columns_from_insert` (mysql features) is enabled for every
   MariaDB, but INSERT ... RETURNING only exists since MariaDB 10.5; on 10.4
   it produces SQL syntax errors during migrate/bulk_create.  Disabled below.

Use as 'ENGINE': 'dashboard.db_backends.mariadb'.
"""
from django.db.backends.mysql import base as mysql_base
from django.db.backends.mysql.features import DatabaseFeatures as MysqlFeatures
from django.db.utils import NotSupportedError


class DatabaseFeatures(MysqlFeatures):
    @property
    def can_return_columns_from_insert(self):
        if self.connection.mysql_is_mariadb:
            # RETURNING arrived in MariaDB 10.5; 10.4 must use LAST_INSERT_ID.
            return self.connection.mysql_version >= (10, 5)
        return False

    can_return_rows_from_bulk_insert = property(
        lambda self: self.can_return_columns_from_insert
    )


class DatabaseWrapper(mysql_base.DatabaseWrapper):
    vendor = 'mysql'
    features_class = DatabaseFeatures

    def check_database_version_supported(self):
        # Django 6 requires MariaDB >= 10.11; XAMPP 10.4 is acceptable for
        # this development dummy database (feature set used is compatible).
        if getattr(self, 'mysql_is_mariadb', False):
            if self.mysql_version < (10, 4):
                raise NotSupportedError(
                    'MariaDB 10.4 or later is required (found %s).'
                    % self.mysql_version)
            return
        super().check_database_version_supported()
