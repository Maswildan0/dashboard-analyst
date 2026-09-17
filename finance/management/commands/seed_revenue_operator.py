"""Create (or update) the first manual-revenue operator account.

Without an operator account every gated manual-revenue control disappears:
finance.permissions.capabilities returns all-false, so "+ Input Manual" and the
row-action menu entries never render and the feature looks broken. This command
grants exactly the six permissions the feature checks.

Run:
    python manage.py seed_revenue_operator                      # admin / random
    python manage.py seed_revenue_operator --username wildan --password rahasia
    python manage.py seed_revenue_operator --superuser          # + all rights

Idempotent: re-running updates the existing account instead of duplicating it.
The password is only replaced when one is supplied; otherwise an existing
operator keeps its current password.
"""
import secrets

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError

from finance.permissions import ACTION_PERMS

GROUP_NAME = 'Revenue Operator'


class Command(BaseCommand):
    help = 'Create/update the manual-revenue operator account with its permissions.'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='admin')
        parser.add_argument('--password', default='',
                           help='Omit to be prompted; a generated one is printed.')
        parser.add_argument('--email', default='')
        parser.add_argument('--superuser', action='store_true',
                           help='Grant superuser (all permissions) as well.')
        parser.add_argument('--force-password', action='store_true',
                           help='Replace the password of an existing account.')

    def handle(self, *args, **options):
        User = get_user_model()
        username = options['username']
        password = options['password']

        group, _ = Group.objects.get_or_create(name=GROUP_NAME)
        wanted = [p for p in ACTION_PERMS.values() if p]
        missing = []
        perms = []
        for label in wanted:
            app_label, codename = label.split('.', 1)
            perm = Permission.objects.filter(
                content_type__app_label=app_label, codename=codename).first()
            if perm is None:
                missing.append(label)
            else:
                perms.append(perm)
        if missing:
            raise CommandError(
                'Permission berikut belum ada — jalankan migrasi lebih dulu: '
                + ', '.join(missing))
        group.permissions.set(perms)

        user, created = User.objects.get_or_create(username=username)
        if options['email']:
            user.email = options['email']

        generated = False
        if created or options['force_password']:
            if not password:
                password = secrets.token_urlsafe(9)
                generated = True
            user.set_password(password)
        if options['superuser']:
            user.is_superuser = True
            user.is_staff = True
        user.is_active = True
        user.save()
        user.groups.add(group)

        # The account's own permissions are left untouched: group membership is
        # the intended grant path, and superusers bypass checks anyway.
        state = 'dibuat' if created else 'diperbarui'
        self.stdout.write(self.style.SUCCESS(
            f'Operator {state}: {username} (grup "{GROUP_NAME}", {len(perms)} permission)'))
        if options['superuser']:
            self.stdout.write('  superuser: ya (semua izin)')
        if generated:
            self.stdout.write(self.style.WARNING(f'  password sementara: {password}'))
            self.stdout.write('  ganti setelah login pertama.')
        self.stdout.write('  login di /login/')
