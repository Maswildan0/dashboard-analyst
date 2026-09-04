"""Seed revenue master data: OrganizationUnits (from the PP mapping) and the
PP->organization mapping from the master prompt (section 12), plus revenue
accounts for TF / NTF_RESEARCH / NTF_PROJECT classification.

Run: python manage.py seed_revenue_master
Idempotent: re-running updates/keeps existing rows, never duplicates.
"""
from django.core.management.base import BaseCommand
from finance.models import (
    Campus,
    OrganizationUnit,
    PPMaster,
    RevenueAccount,
    RevenueCategory,
)

# PP -> organization (owner). Duplicate codes under the same owner removed.
PP_OWNER_MAP = {
    'DIREKTORAT AKADEMIK': ['1104'],
    'DIREKTORAT ASUS': ['2302'],
    'DIREKTORAT BTP': ['9299', '4902'],
    'DIREKTORAT KEUANGAN': ['2102', '2101'],
    'DIREKTORAT PADMI': ['3101'],
    'DIREKTORAT PDPB': ['1103', '1302', '3204'],
    'DIREKTORAT PPM': ['4102'],
    'DITMAWA': ['4301'],
    'RI-CCSL': ['9106', '9114', '9118', '9120', '9123', '9130', '9131', '9138', '9141', '9144'],
    'RI-DHSW': ['9109', '9111', '9116', '9121', '9125', '9127', '9128', '9135', '9136', '9142', '9143'],
    'RI-IBSE': ['9110', '9117', '9119', '9122', '9124', '9126', '9129', '9133', '9134', '9140', '9145', '9146'],
    "SDG'S": ['9115'],
    'TUJ': ['6906'],
    'TUP': ['8911'],
    'TUS': ['7905'],
}

# Seed account classification (TF / NTF_RESEARCH / NTF_PROJECT). These mirror
# the groups in the master prompt. GL rows whose account is NOT here remain
# UNMAPPED there is intentionally no catch-all.
ACCOUNT_SEED = [
    # Tuition Fee (chart of accounts per user: registration + education)
    ('4111101', 'Pend. Pendaftaran', 'TF', 'TF'),
    ('4121135', 'Pendapatan Pddk Pelatihan, Seminar, Workshop, dan Konferensi', 'TF', 'TF'),
    ('4121199', 'Pend. Pddk Lainnya', 'TF', 'TF'),
    # NTF Research (hibah/penelitian/pengabdian eksternal, per user list)
    ('4151102', 'Penerimaan Hibah Pengabdian Masyarakat Dana Eksternal', 'NTF_RESEARCH', 'NTF_RESEARCH'),
    ('4151107', 'Penerimaan Penelitian Dana Eksternal', 'NTF_RESEARCH', 'NTF_RESEARCH'),
    ('4151108', 'Penerimaan Pengabdian Masyarakat Dana Eksternal', 'NTF_RESEARCH', 'NTF_RESEARCH'),
    ('4251101', 'Penerimaan Hibah Penelitian Dana Eksternal ( Dengan Pembatasan )', 'NTF_RESEARCH', 'NTF_RESEARCH'),
    ('4251102', 'Penerimaan Hibah Pengabdian Masyarakat Dana Eksternal (Dengan Pembatasan)', 'NTF_RESEARCH', 'NTF_RESEARCH'),
    ('4251107', 'Penerimaan Penelitian Dana Eksternal (Dengan Pembatasan)', 'NTF_RESEARCH', 'NTF_RESEARCH'),
    ('4251108', 'Penerimaan Pengabdian Masyarakat Dana Eksternal (Dengan Pembatasan)', 'NTF_RESEARCH', 'NTF_RESEARCH'),
    # NTF Project: contract projects + sertifikasi/konsultasi/layanan per user
    ('4131104', 'Pend. Pelatihan Sertifikasi', 'NTF_PROJECT', 'NTF_PROJECT'),
    ('4140101', 'Pendapatan Kerja Sama Proyek', 'NTF_PROJECT', 'NTF_PROJECT'),
    ('4140102', 'Pendapatan Jasa Layanan Proyek', 'NTF_PROJECT', 'NTF_PROJECT'),
    ('4141101', 'Pend. Jasa Konsultasi Manajemen', 'NTF_PROJECT', 'NTF_PROJECT'),
    ('4261101', 'Pend. Donasi ( Dengan Pembatasan )', 'NTF_PROJECT', 'NTF_PROJECT'),
    ('4911101', 'Pend. Pengelolaan Asrama', 'NTF_PROJECT', 'NTF_PROJECT'),
    ('4911102', 'Pend. pengelolaan Gedung', 'NTF_PROJECT', 'NTF_PROJECT'),
    ('4911103', 'Pend. pengelolaan Kantin', 'NTF_PROJECT', 'NTF_PROJECT'),
    ('4911104', 'Pend. pengelolaan Lahan', 'NTF_PROJECT', 'NTF_PROJECT'),
    ('4911199', 'Pend. pengelolaan Lainnya', 'NTF_PROJECT', 'NTF_PROJECT'),
    ('4991199', 'Pend. Lain-Lain', 'NTF_PROJECT', 'NTF_PROJECT'),
]


class Command(BaseCommand):
    help = 'Seed revenue master data (org units, PP mapping, revenue accounts).'

    def handle(self, *args, **options):
        campus, _ = Campus.objects.get_or_create(code='BDG', defaults={'name': 'Bandung'})
        orgs = {}
        for owner_name, pp_codes in PP_OWNER_MAP.items():
            code = ''.join(ch for ch in owner_name.upper() if ch.isalnum())[:30] or 'ORG'
            org, _ = OrganizationUnit.objects.get_or_create(
                code=code,
                defaults={
                    'name': owner_name,
                    'campus': campus,
                    'unit_type': 'OTHER',
                },
            )
            orgs[owner_name] = org
            for pp_code in pp_codes:
                PPMaster.objects.update_or_create(
                    pp_code=pp_code,
                    defaults={'organization_unit': org, 'is_active': True},
                )
        self.stdout.write(f'seeded {OrganizationUnit.objects.count()} org units, {PPMaster.objects.count()} PP codes')

        cats = {c.code: c for c in RevenueCategory.objects.filter(is_active=True)}
        if 'TF' not in cats or 'NTF_PROJECT' not in cats or 'NTF_RESEARCH' not in cats:
            self.stderr.write('RevenueCategory TF/NTF_PROJECT/NTF_RESEARCH missing run seed_financial_data first')
        created = 0
        seeded = []
        for account_code, account_name, cat_code, subcat in ACCOUNT_SEED:
            if cat_code not in cats:
                continue
            seeded.append(account_code)
            acc, was_created = RevenueAccount.objects.get_or_create(
                account_code=account_code,
                defaults={
                    'account_name': account_name,
                    'revenue_category': cats[cat_code],
                    'subcategory': subcat,
                    'is_active': True,
                },
            )
            created += int(was_created)
            if not was_created:
                # refresh name/category in case the chart of accounts changed
                changed = False
                if acc.account_name != account_name:
                    acc.account_name = account_name
                    changed = True
                if acc.revenue_category_id != cats[cat_code].pk:
                    acc.revenue_category = cats[cat_code]
                    changed = True
                if not acc.is_active:
                    acc.is_active = True
                    changed = True
                if changed:
                    acc.save(update_fields=['account_name', 'revenue_category', 'is_active'])
        # Deactivate accounts that used to be seeded but are no longer part
        # of the chart of accounts (e.g. superseded TF codes) so they never
        # surface as live rows.
        stale = RevenueAccount.objects.filter(revenue_category__in=cats.values()).exclude(account_code__in=seeded)
        n_stale = stale.update(is_active=False)
        # Pend. Pendaftaran (4111101) is periodic income: its GL expand is
        # scoped to the exact selected period, never lifetime history.
        RevenueAccount.objects.filter(account_code='4111101').update(detail_history_mode='PERIOD_ONLY')
        self.stdout.write(f'revenue accounts: {RevenueAccount.objects.count()} (created {created}, deactivated {n_stale})')
        self.stdout.write(self.style.SUCCESS('Done.'))
