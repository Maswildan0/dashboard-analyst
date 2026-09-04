"""Seed a rich, deterministic REVENUE DEMO dataset (no SIMKUG needed).

Populates:
- Projects (NTF) with real-looking names/values across PP/organizations.
- RevenueLedger GL rows for 2025 (Jan-Aug) and 2026 (Jan-Aug):
    * TF rows  per (PP x TF account)        -> Data TF page
    * Research rows per (PP x research acct) -> Data NTF Research page
    * NTF Project termin rows referencing the project name -> NTF Project page
- RKA versions/budgets (annual == monthly phasing) for 2025 & 2026.
- GL<->Project mapping for the NTF project rows.
- Frozen monthly + project snapshots: closes every period except 2026-Aug
  (left OPEN to demo live data + period status).

Idempotent: run `python manage.py seed_revenue_demo` to rebuild.
"""
import random
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from finance.models import (
    Campus,
    FinancialPeriod,
    GLProjectMapping,
    NtfReportSnapshot,
    OrganizationUnit,
    PPMaster,
    Project,
    ProjectAlias,
    RevenueAccount,
    RevenueBudget,
    RevenueBudgetMonthly,
    RevenueCategory,
    RevenueLedger,
    RevenueMonthlySnapshot,
    ProjectMonthlySnapshot,
    RkaVersion,
    SimkugSyncLog,
)
from finance.services.account_classification import normalize_description
from finance.management.commands._data_research import RESEARCH_OBJECTS
try:
    from finance.management.commands._data_research2 import RESEARCH_EXTRA
except Exception:
    RESEARCH_EXTRA = []
from finance.management.commands._data_project import PROJECT_OBJECTS

D = Decimal


def _q(v, places=2):
    return D(str(v)).quantize(D('0.1') ** places, rounding=ROUND_HALF_UP)


def _rupiah(v):
    return 'Rp' + f'{int(v):,}'.replace(',', '.')


# ---------------------------------------------------------------------------
# Project seed: (project_number, pp_code, unit, name, project_value)
# ---------------------------------------------------------------------------
PROJECT_SEED = [
    ('P-9130-001', '9130', 'Divisi Digital',    'Pengembangan Smart Campus Telkom University', 12_000_000_000),
    # PERSIAPAN: contract in master but no recognition yet (stays out of the
    # revenue list until GL arrives; project_value > 0 per dummy rule).
    ('P-9130-002', '9130', 'Divisi Digital',    'Riset Peta Jalan Transformasi Digital',         1_200_000_000),
    ('P-9130-003', '9130', 'Divisi Konstruksi', 'Revitalisasi Gedung Rektorat',                 4_900_000_000),
    ('P-9130-004', '9130', 'Divisi Telekom',    'Penguatan Infrastruktur Jaringan Kampus',      6_700_000_000),
    ('P-9106-001', '9106', 'Divisi Telekom',    'Pembangunan Fiber Optik Antar Gedung',          3_200_000_000),
    ('P-9106-002', '9106', 'Divisi Digital',    'Instalasi Jaringan WiFi Kampus Merdeka',       1_250_000_000),
    ('P-2302-001', '2302', 'Divisi Digital',    'Penerapan ATCS Kota Bandung',                   1_500_000_000),
    ('P-2302-002', '2302', 'Divisi Energi',     'Audit Energi dan Efisiensi Daya',                 780_000_000),
    ('P-9299-001', '9299', 'Divisi Digital',    'Digitalisasi Arsip Kepegawaian',                800_000_000),
    ('P-9109-001', '9109', 'Divisi Telekom',    'Penguatan Jaringan Kampus Terpadu',             5_400_000_000),
    ('P-9109-002', '9109', 'Divisi Telekom',    'Upgrade Perangkat Radio Akses',                 2_150_000_000),
    ('P-9110-001', '9110', 'Divisi Digital',    'Sistem Informasi Akademik Terintegrasi',        6_100_000_000),
    ('P-9110-002', '9110', 'Divisi Digital',    'Pengembangan Aplikasi Mobile Mahasiswa',        2_800_000_000),
    ('P-9131-001', '9131', 'Divisi Konstruksi', 'Penataan Laboratorium Riset Terpadu',           2_400_000_000),
    ('P-9131-002', '9131', 'Divisi Konstruksi', 'Renovasi Ruang Kelas dan Auditorium',           1_950_000_000),
    ('P-9120-001', '9120', 'Divisi Konstruksi', 'Pembangunan Gedung Serbaguna Kampus',           8_700_000_000),
    ('P-9120-002', '9120', 'Divisi Konstruksi', 'Pembangunan Fasilitas Olahraga Indoor',        4_300_000_000),
    ('P-9114-001', '9114', 'Divisi Energi',     'Pemasangan Solar Panel Atap Gedung',            4_200_000_000),
    ('P-9123-001', '9123', 'Divisi Digital',    'Platform Data Analytics Kampus',                2_000_000_000),
    ('P-9123-002', '9123', 'Divisi Digital',    'Integrasi API Layanan Akademik',                1_100_000_000),
    ('P-9117-001', '9117', 'Divisi Digital',    'Keamanan Siber dan Security Operation Center',   3_600_000_000),
    ('P-9117-002', '9117', 'Divisi Digital',    'Sosialisasi dan Pelatihan Keamanan Informasi',    650_000_000),
    ('P-4301-001', '4301', 'Divisi Digital',    'Pengadaan Perangkat Multimedia Kreatif',          950_000_000),
    ('P-4301-002', '4301', 'Divisi Telekom',    'Studio Produksi Konten Digital',                1_480_000_000),
    ('P-4102-001', '4102', 'Divisi Digital',    'Pengembangan LMS dan E-Learning',               2_600_000_000),
    ('P-4102-002', '4102', 'Divisi Energi',     'Monitoring Konsumsi Energi Real-Time',            890_000_000),
]

# Contract codes (per project number)
CONTRACT = {
    'P-9130-001': 'CT-2024-011', 'P-9130-003': 'CT-2025-002', 'P-9130-004': 'CT-2025-007',
    'P-9106-001': 'CT-2025-003', 'P-9106-002': 'CT-2026-008',
    'P-2302-001': 'CT-2026-001', 'P-2302-002': 'CT-2026-012',
    'P-9299-001': 'CT-2026-002', 'P-9109-001': 'CT-2025-008', 'P-9109-002': 'CT-2026-009',
    'P-9110-001': 'CT-2024-023', 'P-9110-002': 'CT-2026-010',
    'P-9131-001': 'CT-2026-005', 'P-9131-002': 'CT-2026-013',
    'P-9120-001': 'CT-2025-014', 'P-9120-002': 'CT-2025-016',
    'P-9114-001': 'CT-2026-004', 'P-9123-001': 'CT-2026-006', 'P-9123-002': 'CT-2026-014',
    'P-9117-001': 'CT-2026-003', 'P-9117-002': 'CT-2026-011',
    'P-4301-001': 'CT-2026-007', 'P-4301-002': 'CT-2026-015',
    'P-4102-001': 'CT-2026-016', 'P-4102-002': 'CT-2026-017',
}

# Which projects already run in 2025 (older ones), with target lifetime share
# for the whole demo (2025+2026); the rest start in 2026.
# Projects with a signed contract but no termin yet (stay PERSIAPAN;
# they only appear once GL is recognised).
PREPARATION_PROJECTS = {'P-9130-002'}

PROJECT_2025 = {
    'P-9130-001': D('0.55'), 'P-9130-003': D('0.40'), 'P-9130-004': D('0.35'),
    'P-9109-001': D('0.40'), 'P-9110-001': D('0.35'),
    'P-9120-001': D('0.45'), 'P-9120-002': D('0.30'),
    'P-9114-001': D('0.30'), 'P-9117-001': D('0.30'),
}
# lifetime share target by end of 2026 (>= value -> FULLY/NEEDS_REVIEW demo)
PROJECT_2026 = {
    'P-9130-001': D('0.70'), 'P-9130-003': D('0.55'), 'P-9130-004': D('0.60'),
    'P-9106-001': D('0.80'), 'P-9106-002': D('0.70'),
    'P-2302-001': D('0.85'), 'P-2302-002': D('0.65'),
    'P-9299-001': D('0.60'),
    'P-9109-001': D('0.65'), 'P-9109-002': D('0.75'),
    'P-9110-001': D('0.75'), 'P-9110-002': D('0.80'),
    'P-9131-001': D('0.45'), 'P-9131-002': D('0.55'),
    'P-9120-001': D('0.60'), 'P-9120-002': D('0.50'),
    'P-9114-001': D('0.55'),
    'P-9123-001': D('0.90'), 'P-9123-002': D('0.70'),
    'P-9117-001': D('0.70'), 'P-9117-002': D('0.55'),
    'P-4301-001': D('1.00'), 'P-4301-002': D('0.85'),
    'P-4102-001': D('0.80'), 'P-4102-002': D('0.60'),
}

# Project whose GL uses TWO accounts (shows "Multi Akun · N").
MULTI_ACCOUNT_PROJECTS = {'P-9120-001', 'P-9131-001', 'P-9130-004', 'P-9110-002', 'P-9109-002', 'P-4301-002'}

# Monthly seasonality (Jan..Aug) applied to recurring TF/research income.
SEASON = [D('0.82'), D('0.86'), D('0.9'), D('0.95'), D('1.0'), D('1.08'), D('1.04'), D('0.98')]
GROWTH_2026 = D('1.08')  # vs same month 2025

# ---------------------------------------------------------------------------
# TF education programs (real chart of accounts + program names, per user).
# One entry = one program: (account_code, pp_code, program_name, month, base).
# `month` is the month (1..8) the program revenue is recognised in 2026;
# 2025 uses the same program names spread Jan-Aug. GL rows carry the program
# name in the description so PP+NAME mapping attaches them to the Project.
# ---------------------------------------------------------------------------
TF_REG_PP = '3101'   # Pend. Pendaftaran -> DIREKTORAT PADMI

TF_PROGRAMS = [
    # 4111101 Pend. Pendaftaran (one program, PP 3101)
    ('4111101', '3101', 'Pendapatan Pendaftaran PIN SMBB', None, D('0')),

    # 4121135 Pendapatan Pddk Pelatihan, Seminar, Workshop, dan Konferensi
    ('4121135', '1103', 'Pelatihan dan Sertifikasi Public Speaking Universitas Negeri Surabaya', 5, D('0')),
    ('4121135', '3204', 'Pendapatan dan Beban TF Kegiatan BIPA KNB Semester 2 T.A. 2025-2026', 4, D('0')),
    ('4121135', '3204', 'Pendapatan dan Beban TF Pusat Bahasa Bulan April 2026', 4, D('0')),
    ('4121135', '3204', 'Pendapatan dan Beban TF Pusat Bahasa Bulan Februari-Maret 2026 (Admisi Kelas Internasional)', 3, D('0')),
    ('4121135', '3204', 'Pendapatan dan Beban TF Pusat Bahasa Bulan Januari 2026 (Admisi Kelas Internasional)', 1, D('0')),
    ('4121135', '3204', 'Pendapatan dan Beban TF Pusat Bahasa Februari 2026', 2, D('0')),
    ('4121135', '3204', 'Pendapatan dan Beban TF Pusat Bahasa Kegiatan English for Teaching Guru TK Yayasan Pendidikan Telkom', 6, D('0')),
    ('4121135', '3204', 'Pendapatan dan Beban TF Pusat Bahasa Maret 2026', 3, D('0')),
    ('4121135', '3204', 'Pendapatan TF Pusat Bahasa bulan Januari 2026', 1, D('0')),
    ('4121135', '3204', 'TF Outstanding Pusat Bahasa Oktober-Desember 2025', 1, D('0')),
    ('4121135', '3204', 'TF Pusat Bahasa Bulan April 2026 (Admisi Kelas Internasional)', 4, D('0')),
    ('4121135', '3204', 'TF Pusat Bahasa Bulan Juli 2026', 7, D('0')),
    ('4121135', '3204', 'TF Pusat Bahasa Bulan Juni 2026', 6, D('0')),
    ('4121135', '3204', 'TF Pusat Bahasa Bulan Juni 2026 (Admisi Calon Mahasiswa Kelas Kerjasama)', 6, D('0')),
    ('4121135', '3204', 'TF Pusat Bahasa Bulan Mei 2026', 5, D('0')),
    ('4121135', '3204', 'TF Pusat Bahasa Bulan Mei 2026 (Admisi Calon Mahasiswa Kelas Kerjasama)', 5, D('0')),
    ('4121135', '4902', 'ICOICT TAHUN 2026 INTERNAL', 7, D('0')),
    ('4121135', '4902', 'Kegiatan Webinar SAI Periode I - Tahun 2026', 3, D('0')),
    ('4121135', '9119', 'Digital Marketing Periode Februari-Maret 2026 Training & Certification', 3, D('0')),
    ('4121135', '9119', 'Pelaksanaan Program Pelatihan & Sertifikasi Content Creator Periode Maret-April 2026 Badan Nasional Sertifikasi Profesi (BNSP)', 4, D('0')),
    ('4121135', '9119', 'Pelaksanaan Program Pelatihan & Sertifikasi Digital Public Relation Periode Maret-April 2026 Badan Nasional Sertifikasi Profesi (BNSP)', 4, D('0')),
    ('4121135', '9127', 'Sertifikasi Junior Public Relations Batch 1 2026', 5, D('0')),
    ('4121135', '9135', 'Workshop Design Thinking 2026', 6, D('0')),
    ('4121135', '9299', 'ICOEINS 2026 Internal', 8, D('0')),
    ('4121135', '9299', 'ICSMech 2026 Internal', 8, D('0')),
    ('4121135', '9299', 'Kegiatan Company Visit Mahasiswa D3 Perhotelan 2024', 6, D('0')),
    ('4121135', '9299', 'PELATIHAN DAN SERTIFIKASI AKUNTANSI 1 2026', 7, D('0')),
    ('4121135', '9299', 'QRMO 1 2026', 5, D('0')),
    ('4121135', '9299', 'QRMO 2 2026', 7, D('0')),
    ('4121135', '9299', 'The 2026 International Conference on Advancement in Data Science, E-learning and Information System (ICADEIS) Internal', 8, D('0')),

    # 4121199 Pend. Pddk Lainnya
    ('4121199', '1104', 'Assesment RPL 2026', 6, D('0')),

]

# Research: per-PP monthly base
RESEARCH_PP_BASE = {
    '9130': 42_000_000, '9110': 36_000_000, '9109': 30_000_000,
    '9115': 26_000_000, '4102': 22_000_000,
    '9117': 20_000_000, '9123': 18_000_000, '9131': 15_000_000,
    '9120': 17_000_000, '9114': 12_000_000, '9106': 14_000_000,
}
RESEARCH_ACCOUNTS = [
    ('4130101', D('0.72')),
    ('4130102', D('0.28')),
]

MONTHS = list(range(1, 9))  # Jan..Aug


class Command(BaseCommand):
    help = 'Seed deterministic revenue demo data (2025-2026 Jan-Aug).'

    def handle(self, *args, **options):
        random.seed(7)
        call_command('seed_revenue_master')  # org/PP/account masters (idempotent)

        with transaction.atomic():
            self._wipe()
            self._seed_projects()
            self._seed_gl()
            self._seed_research_objects()
            self._seed_project_objects()
            self._match_projects()
            self._allocate_tf_targets()
            self._seed_rka()

        self._close_historical_periods()
        self._summary()

    # ------------------------------------------------------------------
    def _wipe(self):
        SimkugSyncLog.objects.all().delete()
        RevenueMonthlySnapshot.objects.all().delete()
        ProjectMonthlySnapshot.objects.all().delete()
        GLProjectMapping.objects.all().delete()
        ProjectAlias.objects.all().delete()
        NtfReportSnapshot.objects.all().delete()
        RevenueLedger.objects.all().delete()
        Project.objects.all().delete()
        RevenueBudgetMonthly.objects.all().delete()
        RevenueBudget.objects.all().delete()
        RkaVersion.objects.all().delete()
        # periods used by the demo are reopened (closed state will be re-applied)
        FinancialPeriod.objects.filter(year__in=(2025, 2026), month__lte=8) \
            .update(is_closed=False)
        self.stdout.write('wiped previous revenue demo rows')

    def _period(self, year, month):
        period, _ = FinancialPeriod.objects.get_or_create(
            year=year, month=month,
            defaults={
                'period_start': date(year, month, 1),
                'period_end': date(year, month, 28),
            },
        )
        return period

    def _seed_projects(self):
        self.orgs = {o.name: o for o in OrganizationUnit.objects.all()}
        self.pp_by_code = {p.pp_code: p for p in PPMaster.objects.filter(is_active=True)}
        self.accounts = {
            a.account_code: a
            for a in RevenueAccount.objects.filter(is_active=True)
        }
        self.projects = {}
        self.unit_by_project = {}
        for number, pp_code, unit, name, value in PROJECT_SEED:
            pp = self.pp_by_code.get(pp_code)
            if pp is None:
                continue
            proj = Project.objects.create(
                project_number=number,
                pp=pp,
                contract_code=CONTRACT.get(number, ''),
                project_name=name,
                organization_unit=pp.organization_unit,
                campus=Campus.objects.filter(code='BDG').first(),
                project_value=D(value),
                source_status=('PERSIAPAN' if number in PREPARATION_PROJECTS else 'AKTIF'),
                first_seen_period=self._period(2025 if number in PROJECT_2025 else 2026, 1),
                last_seen_period=self._period(2026, 8),
                is_active=True,
            )
            self.projects[number] = proj
            self.unit_by_project[number] = unit
            # NTF report snapshot supplies the raw Unit metadata (per source).
            NtfReportSnapshot.objects.create(
                project=proj,
                period=self._period(2026, 8),
                source_project_value=D(value),
                source_total_recognized=D('0'),
                source_current_year_recognized=D('0'),
                unit_raw=unit,
                organization_raw=pp.organization_unit.name if pp.organization_unit else '',
                project_name_raw=name,
                contract_code_raw=CONTRACT.get(number, ''),
            )

    # ------------------------------------------------------------------
    def _add_gl(self, period, pp_code, account_code, account_name, desc,
                credit, *, day=None, prefix=''):
        if credit <= 0:
            return
        pp = self.pp_by_code.get(pp_code)
        if pp is None:
            return
        day = day or random.randint(2, 26)
        posting = date(period.year, period.month, day)
        idx = RevenueLedger.objects.filter(period=period).count()
        tx = f'{prefix or "GL"}-{period.year}{period.month:02d}-{pp_code}-{account_code}-{idx}'
        RevenueLedger.objects.create(
            source_transaction_id=tx,
            posting_date=posting,
            period=period,
            voucher_number=f'V-{period.month:02d}{idx:03d}',
            document_number=f'DOC-{idx:05d}',
            account_code_raw=account_code,
            account_name_raw=account_name,
            description_raw=desc,
            pp_code_raw=pp_code,
            revenue_account=self.accounts.get(account_code),
            pp=pp,
            description_normalized=normalize_description(desc),
            debit=D('0'),
            credit=_q(credit),
            source_balance=_q(credit),
        )

    def _tf_program_value(self, name):
        """Deterministic nominal for a TF program (20jt..520jt) derived from
        its name so re-seeds are stable and sizes look realistic."""
        h = sum(ord(c) for c in name)
        return _q(D(20_000_000 + (h % 500) * 1_000_000))

    def _seed_tf_programs(self):
        """Create TF program Projects + their GL rows (per real program
        names). Pendaftaran (4111101, PP 3101) is recognised every month as
        PIN SMBB channels; other programs recognise in their month."""
        reg_acc = self.accounts.get('4111101')
        seq = {}
        for acc_code, pp_code, name, month, _base in TF_PROGRAMS:
            pp = self.pp_by_code.get(pp_code)
            acc = self.accounts.get(acc_code)
            if pp is None or acc is None:
                continue
            seq[acc_code] = seq.get(acc_code, 0) + 1
            number = f'TF-{acc_code}-{pp_code}-{seq[acc_code]:02d}'
            proj = Project.objects.create(
                project_number=number,
                pp=pp,
                project_name=name,
                organization_unit=pp.organization_unit,
                campus=Campus.objects.filter(code='BDG').first(),
                project_value=D('0'),   # no contract value; RKA is the target
                source_status='AKTIF',
                is_active=True,
            )
            self.projects[number] = proj
            # Recognise GL in 2026 (the program's month, or monthly for
            # Pendaftaran) and a smaller 2025 analogue.
            proj.project_value = D('0')  # recomputed below as RKA allocation
            if acc_code == '4111101':
                for year in (2025, 2026):
                    for mi, mon in enumerate(MONTHS):
                        factor = SEASON[mi] * (GROWTH_2026 if year == 2026 else D('1'))
                        total = _q(self._tf_program_value(name) * factor)
                        for share, channel in (
                                (D('0.40'), 'BNI PIN SMBB'), (D('0.25'), 'Mandiri PIN SMBB'),
                                (D('0.20'), 'BRI PIN SMBB'), (D('0.15'), 'BTN PIN SMBB')):
                            self._add_gl(
                                self._period(year, mon), pp_code, acc_code,
                                acc.account_name,
                                f'Penerimaan {name} {channel} - {year}-{mon:02d}',
                                _q(total * share), prefix='TF',
                            )
            else:
                value = self._tf_program_value(name)
                for year in (2025, 2026):
                    mon = month if year == 2026 else (month - 1 or 1)
                    factor = GROWTH_2026 if year == 2026 else D('1')
                    self._add_gl(
                        self._period(year, mon), pp_code, acc_code,
                        acc.account_name,
                        f'Penerimaan {name} - {year}-{mon:02d}',
                        _q(value * factor), prefix='TF',
                    )

    def _seed_gl(self):
        # ---- TF education programs (real program names, per user list) ----
        self._seed_tf_programs()

        # ---- NTF project termin (mapped to projects afterwards) ----
        for number, proj in self.projects.items():
            if not proj.project_value:
                continue  # NO_REVENUE demo project
            main_acc = '4140101'
            extra_acc = '4140102' if number in MULTI_ACCOUNT_PROJECTS else None

            # 2025 portion
            if number in PROJECT_2025:
                share = PROJECT_2025[number]
                self._project_terms(proj, 2025, share, main_acc, extra_acc)
            # 2026 portion (of the lifetime value)
            if number in PROJECT_2026:
                lifetime_share = PROJECT_2026[number]
                # subtract what 2025 already delivered
                already = (share_2025 := PROJECT_2025.get(number, D('0')))
                remaining_share = max(D('0'), lifetime_share - already)
                self._project_terms(proj, 2026, remaining_share, main_acc, extra_acc)

    def _project_terms(self, proj, year, share, main_acc, extra_acc):
        """Recognize `share` of project_value as 1..n termin rows in `year`."""
        if share <= 0:
            return
        value = proj.project_value
        total = _q(value * share)
        n_terms = random.randint(2, 4)
        splits = self._split(total, n_terms)

        # spread over Jan..Aug (later months for later terms)
        months_pool = list(MONTHS)
        random.shuffle(months_pool)
        used_acc = main_acc
        for i, amount in enumerate(splits):
            if extra_acc and i % 2 == 1:
                used_acc = extra_acc
            else:
                used_acc = main_acc
            month = months_pool[i % len(months_pool)]
            period = self._period(year, month)
            acc = self.accounts.get(used_acc)
            label = f'Termin {i + 1} {proj.project_name}'
            self._add_gl(
                period, proj.pp.pp_code, used_acc,
                acc.account_name if acc else '',
                label, amount, prefix='NTF',
            )

    @staticmethod
    def _split(total, n):
        parts = []
        remaining = total
        for i in range(n):
            if i == n - 1:
                parts.append(remaining)
            else:
                frac = D(str(random.uniform(0.25, 0.45)))
                piece = _q(remaining * frac)
                parts.append(piece)
                remaining -= piece
        return parts

    # ------------------------------------------------------------------
    def _match_projects(self):
        """Map GL rows to projects: NTF_PROJECT rows + TF program rows
        (both carry the project/program name in the description, PP-scoped)."""
        updated = 0
        for row in (RevenueLedger.objects
                    .filter(revenue_account__revenue_category__code__in=('NTF_PROJECT', 'NTF_RESEARCH', 'TF'))
                    .select_related('pp').iterator(chunk_size=500)):
            proj = None
            candidates = Project.objects.filter(pp=row.pp) if row.pp else Project.objects.none()
            norm = normalize_description(row.description_raw)
            # Prefer the MOST SPECIFIC (longest) matching project name, so
            # '... Mei 2026 (Admisi Calon Mahasiswa ...)' maps to the Admisi
            # project, not to the shorter 'TF Pusat Bahasa Bulan Mei 2026'.
            best = None
            for p in candidates:
                pn = normalize_description(p.project_name)
                if pn and (pn in norm or norm in pn):
                    if best is None or len(pn) > len(best[1]):
                        best = (p, pn)
            if best is not None:
                proj = best[0]
            if proj is None and candidates.count() == 1:
                proj = candidates.first()
            if proj is None:
                continue
            GLProjectMapping.objects.get_or_create(
                ledger=row,
                defaults={
                    'project': proj,
                    'allocated_amount': abs(row.credit - row.debit),
                    'match_method': 'PP+NAME',
                    'match_confidence': D('0.95'),
                    'match_status': 'AUTO_MATCHED',
                },
            )
            ProjectAlias.objects.get_or_create(
                project=proj, alias_normalized=norm,
                defaults={'alias_raw': row.description_raw[:300], 'is_verified': True},
            )
            updated += 1
        self.stdout.write(f'project GL matched: {updated} rows')

    # ------------------------------------------------------------------
    def _allocate_tf_targets(self):
        """Per-program Nilai Proyek (= Program Master contract value) for the
        dummy DB. Derived ONCE at seed from the program's whole lifetime
        mapped GL (2025 + 2026 rows) so that:

            project_value >= lifetime revenue          (never OVER_RECOGNIZED)
            project_value  = lifetime * (1.10 .. 1.60)  (realistic margin)
            rounded up to a clean nominal (10 jt)

        Deterministic (hash of pp+project number) -> identical after every
        reseed; stored in Project.project_value. NEVER computed at page load.
        Pendaftaran (4111101, PERIOD_ONLY) keeps the same rule: its displayed
        Total equals the selected month only, so value >= month always holds."""
        from django.db.models import Sum as _Sum
        from finance.models import GLProjectMapping as _GPM
        tf = Project.objects.filter(project_number__startswith='TF-')
        for p in tf:
            lifetime = (_GPM.objects
                        .filter(project=p, ledger__period__year__in=(2025, 2026),
                                match_status__in=('AUTO_MATCHED', 'VERIFIED'))
                        .aggregate(s=_Sum('allocated_amount'))['s'] or D('0'))
            if lifetime <= 0:
                continue
            key = sum(ord(c) for c in (p.pp.pp_code + p.project_number))
            # deterministic margin 1.10 .. 1.60
            uplift = D('1.10') + D(key % 51) / D('100')
            contract = _q(lifetime * uplift)
            # round up to next 10 jt so numbers look like contract values
            if contract % D('10000000'):
                contract = (contract // D('10000000') + 1) * D('10000000')
            p.project_value = contract
            p.save(update_fields=['project_value'])

    def _seed_named_objects(self, objects, prefix):
        """Create Project per objek (prefix-) + GL in a deterministic month,
        then map GL via PP+NAME (longest match)."""
        seq = {}
        for acc_code, pp_code, name in objects:
            pp = self.pp_by_code.get(pp_code)
            acc = self.accounts.get(acc_code)
            if pp is None or acc is None:
                continue
            seq[acc_code] = seq.get(acc_code, 0) + 1
            number = f'{prefix}-{acc_code}-{pp_code}-{seq[acc_code]:02d}'
            proj = Project.objects.create(
                project_number=number, pp=pp, project_name=name,
                organization_unit=pp.organization_unit,
                campus=Campus.objects.filter(code='BDG').first(),
                project_value=D('0'), source_status='AKTIF', is_active=True,
            )
            self.projects[number] = proj
            # 2026 GL at a deterministic month; plus 2025 analogue
            h = sum(ord(c) for c in name)
            mon = (h % 8) + 1
            value = _q(D(30_000_000 + (h % 700) * 1_000_000))
            # Dummy contract value (Project Master / Laporan NTF). Deterministic
            # from the object name; stored once on Project.project_value and
            # NEVER computed at page load. Must be >= lifetime recognised total
            # (2025 + 2026 GL) so normal rows are ON PROGRESS / FULLY, never
            # NEEDS REVIEW: contract = lifetime * (1.10 .. 1.50 uplift).
            lifetime_total = _q(value * (D('1') + GROWTH_2026))
            uplift = D('1.10') + D((h // 7) % 41) / D('100')   # 1.10..1.50
            contract = _q(lifetime_total * uplift)
            if contract % D('10000000') != 0:                 # round up to 10jt
                contract = (contract // D('10000000') + 1) * D('10000000')
            proj.project_value = contract
            proj.source_status = 'AKTIF'
            proj.save(update_fields=['project_value', 'source_status'])
            for year in (2025, 2026):
                m = mon if year == 2026 else (mon - 1 or 1)
                factor = GROWTH_2026 if year == 2026 else D('1')
                self._add_gl(self._period(year, m), pp_code, acc_code,
                             acc.account_name,
                             f'Penerimaan {name} - {year}-{m:02d}',
                             _q(value * factor), prefix=prefix)

    def _seed_research_objects(self):
        rows = list(RESEARCH_OBJECTS) + list(RESEARCH_EXTRA)
        self._seed_named_objects(rows, 'RS')

    def _seed_project_objects(self):
        self._seed_named_objects(PROJECT_OBJECTS, 'SRV')

    def _seed_rka(self):
        """RKA per (year x PP x account) for every account that appears in GL;
        annual == sum(monthly phasing)."""
        from django.db.models import Sum
        for year in (2025, 2026):
            version, _ = RkaVersion.objects.get_or_create(
                year=year, version_code='AWAL',
                defaults={'version_name': 'RKA Awal', 'status': 'ACTIVE', 'is_active': True},
            )
            if not version.is_active:
                version.is_active = True
                version.status = 'ACTIVE'
                version.save(update_fields=['is_active', 'status'])

            # per (pp, account): RKA target is derived from GL with a
            # deterministic uplift so some (pp, account) end the demo year
            # ON PROGRESS and others FINISH (realistic mix). The uplift is
            # 1.0..1.18 depending on the account code hash (stable across
            # runs because pp/account codes are fixed).
            gl = (RevenueLedger.objects.filter(period__year=year)
                  .values('pp_id', 'pp__pp_code', 'revenue_account_id',
                          'revenue_account__account_code')
                  .annotate(credit=Sum('credit'), debit=Sum('debit')))
            for g in gl:
                if not g['revenue_account_id']:
                    continue
                net = (g['credit'] or D('0')) - (g['debit'] or D('0'))
                months_seen = MONTHS
                # stable per-account uplift in [1.00, 1.18]
                acc_code = g['revenue_account__account_code'] or ''
                pp_code = g['pp__pp_code'] or ''
                seed_key = sum(ord(c) for c in (pp_code + acc_code))
                uplift = D('1.00') + D(seed_key % 19) / D('100')  # 1.00..1.18
                annual = _q(net / len(months_seen) * 12 * uplift)
                if annual <= 0:
                    continue
                budget, _ = RevenueBudget.objects.update_or_create(
                    rka_version=version, year=year,
                    pp_id=g['pp_id'], revenue_account_id=g['revenue_account_id'],
                    defaults={'annual_budget': annual},
                )
                monthly = [annual / 12 for _ in range(12)]
                monthly = [_q(m) for m in monthly]
                monthly[11] = annual - sum(monthly[:11])
                for m, amount in enumerate(monthly, start=1):
                    RevenueBudgetMonthly.objects.update_or_create(
                        revenue_budget=budget, month=m,
                        defaults={'budget_amount': amount},
                    )
        self.stdout.write('RKA seeded (annual == phasing)')

    # ------------------------------------------------------------------
    def _close_historical_periods(self):
        from finance.services.closing_service import close_revenue_period
        closed = 0
        for year in (2025, 2026):
            for month in MONTHS:
                if year == 2026 and month == 8:
                    continue  # leave current month OPEN
                period = FinancialPeriod.objects.filter(year=year, month=month).first()
                if period is None:
                    continue
                res = close_revenue_period(period)
                if res['status'] in ('CLOSED', 'ALREADY_CLOSED'):
                    closed += 1
        self.stdout.write(f'closed periods: {closed} (2026-08 stays OPEN)')

    # ------------------------------------------------------------------
    def _summary(self):
        rows = RevenueLedger.objects.count()
        projs = Project.objects.filter(project_value__gt=0).count()
        budgets = RevenueBudget.objects.count()
        print('\n=== REVENUE DEMO SUMMARY ===')
        print(f'GL rows          : {rows}')
        print(f'Projects (aktif) : {projs}')
        print(f'RKA budgets      : {budgets}')
        print(f'GL mapping       : {GLProjectMapping.objects.count()}')
        for cat in ('TF', 'NTF_PROJECT', 'NTF_RESEARCH'):
            amt = sum((r.credit - r.debit) for r in
                      RevenueLedger.objects.filter(revenue_account__revenue_category__code=cat)
                      .only('credit', 'debit').iterator(chunk_size=1000))
            print(f'  {cat:14s} total GL 2025-2026: {_rupiah(amt)}')
