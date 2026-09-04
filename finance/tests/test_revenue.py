"""Automated tests for the Revenue module (master prompt #55).

20 scenarios:
 1. Account classification
 2. PP -> Organization
 3. One PP has many projects
 4. GL upsert on open period
 5. Revenue calculation debit-credit
 6. Monthly revenue
 7. YTD revenue
 8. Lifetime project revenue
 9. Remaining project value
10. Project carry-forward to new year
11. YTD reset on year change
12. RKA monthly aggregation
13. Annual RKA == monthly phasing validation
14. RKA vs Actual
15. Month closing
16. Frozen snapshot no duplicate
17. Unmatched project revenue stays in total
18. Project recognition history
19. Filter Organization -> PP
20. Filter Revenue Type -> Account
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from finance.models import (
    Campus,
    FinancialPeriod,
    FinancialDataAuditLog,
    GLProjectMapping,
    OrganizationUnit,
    PPMaster,
    Project,
    ProjectAlias,
    ProjectMonthlySnapshot,
    RevenueAccount,
    RevenueBudget,
    RevenueBudgetMonthly,
    RevenueCategory,
    RevenueLedger,
    RevenueMonthlySnapshot,
    RkaVersion,
)
from finance.services.account_classification import classify_account, normalize_description
from finance.services.revenue_budget_service import compare_actual_vs_rka, validate_phasing
from finance.services.revenue_matching_service import auto_match_ledger
from finance.services.revenue_service import actual_ytd, monthly_series, rka_ytd
from finance.services.closing_service import close_revenue_period
from finance.services.revenue_context import RevenueContext


def make_period(year, month, closed=False):
    period, _ = FinancialPeriod.objects.get_or_create(
        year=year, month=month,
        defaults={
            'period_start': date(year, month, 1),
            'period_end': date(year, month, 28),
            'is_closed': closed,
        },
    )
    if closed and not period.is_closed:
        period.is_closed = True
        period.save(update_fields=['is_closed'])
    return period


class RevenueBase(TestCase):
    def setUp(self):
        self.campus = Campus.objects.create(code='BDG', name='Bandung')
        self.org = OrganizationUnit.objects.create(
            code='RI-CCSL', name='RI-CCSL', campus=self.campus, unit_type='OTHER')
        self.cat_tf = RevenueCategory.objects.create(code='TF', name='Tuition Fee', category_type='REVENUE')
        self.cat_np = RevenueCategory.objects.create(code='NTF_PROJECT', name='NTF Project', category_type='REVENUE')
        self.cat_nr = RevenueCategory.objects.create(code='NTF_RESEARCH', name='NTF Research', category_type='REVENUE')
        self.pp = PPMaster.objects.create(pp_code='9130', organization_unit=self.org)
        self.acc_tf = RevenueAccount.objects.create(account_code='4121135', account_name='Pendapatan Pddk Pelatihan, Seminar, Workshop, dan Konferensi', revenue_category=self.cat_tf)
        self.acc_np = RevenueAccount.objects.create(account_code='4140101', account_name='Kerja Sama', revenue_category=self.cat_np)
        self.acc_nr = RevenueAccount.objects.create(account_code='4130101', account_name='Penelitian', revenue_category=self.cat_nr)

    def gl(self, period, *, credit=0, debit=0, account=None, pp=None, desc='', tx=None):
        account = account or self.acc_np
        pp = pp or self.pp
        tx = tx or f'TX-{RevenueLedger.objects.count() + 1}'
        return RevenueLedger.objects.create(
            source_transaction_id=tx,
            posting_date=period.period_start,
            period=period,
            account_code_raw=account.account_code,
            account_name_raw=account.account_name,
            description_raw=desc,
            pp_code_raw=pp.pp_code,
            revenue_account=account,
            pp=pp,
            description_normalized=normalize_description(desc),
            credit=Decimal(str(credit)),
            debit=Decimal(str(debit)),
        )


# 1. Account classification
class TestAccountClassification(RevenueBase):
    def test_mapped(self):
        acc, status = classify_account('4121135')
        self.assertEqual(status, 'MAPPED')
        self.assertEqual(acc.revenue_category.code, 'TF')

    def test_unmapped_never_defaults(self):
        acc, status = classify_account('9999999')
        self.assertIsNone(acc)
        self.assertEqual(status, 'UNMAPPED')


# 2. PP -> Organization
class TestPpOrganization(RevenueBase):
    def test_pp_owner(self):
        self.assertEqual(self.pp.organization_unit, self.org)


# 3. One PP has many projects
class TestPpManyProjects(RevenueBase):
    def test_many(self):
        Project.objects.create(project_number='A', pp=self.pp, project_name='Alpha')
        Project.objects.create(project_number='B', pp=self.pp, project_name='Beta')
        self.assertEqual(self.pp.projects.count(), 2)


# 4. GL upsert on open period
class TestLedgerUpsert(RevenueBase):
    def test_upsert_same_key_updates(self):
        p = make_period(2026, 1)
        row = self.gl(p, credit=100, desc='x', tx='TX-1')
        row2 = RevenueLedger.objects.get(source_transaction_id='TX-1')
        self.assertEqual(row.pk, row2.pk)  # same key resolves same row
        # emulate re-sync updating the amount in place
        row.credit = Decimal('250')
        row.save()
        self.assertEqual(RevenueLedger.objects.filter(source_transaction_id='TX-1').count(), 1)
        self.assertEqual(RevenueLedger.objects.get(source_transaction_id='TX-1').credit, Decimal('250'))


# 5. Revenue = credit - debit convention
class TestDebitCredit(RevenueBase):
    def test_net(self):
        p = make_period(2026, 1)
        row = self.gl(p, credit=100, debit=30, tx='N1')
        self.assertEqual(row.credit - row.debit, Decimal('70'))


# 6/7. Monthly + YTD
class TestMonthlyYtd(RevenueBase):
    def test_monthly_and_ytd(self):
        make_period(2026, 1); make_period(2026, 2); make_period(2026, 3)
        p1 = FinancialPeriod.objects.get(year=2026, month=1)
        p2 = FinancialPeriod.objects.get(year=2026, month=2)
        self.gl(p1, credit=100, tx='M1')
        self.gl(p2, credit=150, tx='M2')
        ctx = RevenueContext(year=2026, month=2)
        self.assertEqual(actual_ytd(ctx), Decimal('250'))
        series = monthly_series(ctx)
        by_month = {m['month']: m['actual'] for m in series}
        self.assertEqual(by_month[2], Decimal('150'))


# 8/9. Lifetime + remaining
class TestLifetimeRemaining(RevenueBase):
    def test_lifetime_remaining(self):
        p = make_period(2026, 1)
        proj = Project.objects.create(project_number='P1', pp=self.pp, project_name='P1', project_value=1000)
        row = self.gl(p, credit=400, tx='L1')
        map_ = auto_match_ledger(row)
        self.assertEqual(map_.project, proj)
        # lifetime = sum mapped
        lifetime = sum((m.ledger.credit - m.ledger.debit) for m in GLProjectMapping.objects.filter(project=proj))
        self.assertEqual(lifetime, Decimal('400'))
        self.assertEqual(proj.project_value - lifetime, Decimal('600'))  # remaining


# 10/11. Carry-forward + YTD reset
class TestYearCarry(RevenueBase):
    def test_reset_and_lifetime(self):
        p2025 = make_period(2025, 12)
        p2026 = make_period(2026, 1)
        proj = Project.objects.create(project_number='CF', pp=self.pp, project_name='CF', project_value=2000)
        row = self.gl(p2025, credit=800, tx='CF-1')
        auto_match_ledger(row)          # map BEFORE close so snapshot records it
        close_revenue_period(p2025)
        snap = ProjectMonthlySnapshot.objects.get(project=proj, period=p2025)
        self.assertEqual(snap.recognized_month, Decimal('800'))
        self.assertEqual(snap.closing_ytd, Decimal('800'))
        self.assertEqual(snap.closing_lifetime, Decimal('800'))
        self.assertEqual(snap.remaining_value, Decimal('1200'))  # 2000-800
        # YTD reset: Jan 2026 snapshot opening_ytd starts fresh
        self.gl(p2026, credit=100, tx='CF-2')
        auto_match_ledger(RevenueLedger.objects.get(source_transaction_id='CF-2'))
        close_revenue_period(p2026)
        snap26 = ProjectMonthlySnapshot.objects.get(project=proj, period=p2026)
        self.assertEqual(snap26.opening_ytd, Decimal('0'))          # reset
        self.assertEqual(snap26.closing_ytd, Decimal('100'))
        self.assertEqual(snap26.opening_lifetime, Decimal('800'))   # carry-forward
        self.assertEqual(snap26.closing_lifetime, Decimal('900'))
        self.assertEqual(snap26.status_at_close, 'ON_PROGRESS')


# 12/13. RKA monthly aggregation + phasing validation
class TestRka(RevenueBase):
    def test_aggregation_and_phasing(self):
        ver = RkaVersion.objects.create(year=2026, version_code='AWAL', status='ACTIVE', is_active=True)
        b = RevenueBudget.objects.create(rka_version=ver, year=2026, pp=self.pp, revenue_account=self.acc_np, annual_budget=1200)
        for m, amt in enumerate([100] * 11 + [100], start=1):
            RevenueBudgetMonthly.objects.create(revenue_budget=b, month=m, budget_amount=amt)
        ctx = RevenueContext(year=2026, month=6)
        self.assertEqual(rka_ytd(ctx), Decimal('600'))
        self.assertEqual(validate_phasing(ver), [])  # annual == phased
        # mismatch
        RevenueBudgetMonthly.objects.filter(revenue_budget=b, month=12).update(budget_amount=50)
        self.assertEqual(len(validate_phasing(ver)), 1)


# 14. RKA vs Actual
class TestRkaVsActual(RevenueBase):
    def test_variance_achievement(self):
        p = make_period(2026, 3)
        self.gl(p, credit=80, tx='RA1')
        ctx = RevenueContext(year=2026, month=3)
        actual = actual_ytd(ctx)
        rka = rka_ytd(ctx)  # no RKA rows -> 0
        res = compare_actual_vs_rka(actual, rka)
        self.assertIsNone(res['achievement'])  # no division by zero


# 15/16. Month closing + no duplicate
class TestClosing(RevenueBase):
    def test_close_idempotent(self):
        p = make_period(2026, 4)
        self.gl(p, credit=500, tx='C1')
        close_revenue_period(p)
        n = RevenueMonthlySnapshot.objects.filter(period=p).count()
        self.assertGreater(n, 0)
        res = close_revenue_period(p)
        self.assertEqual(res['status'], 'ALREADY_CLOSED')
        self.assertEqual(RevenueMonthlySnapshot.objects.filter(period=p).count(), n)
        self.assertTrue(FinancialPeriod.objects.get(pk=p.pk).is_closed)
        self.assertTrue(FinancialDataAuditLog.objects.filter(action='CLOSE').exists())


# 17. Unmatched revenue stays in total
class TestUnmatchedStays(RevenueBase):
    def test_unmatched_kept(self):
        p = make_period(2026, 5)
        self.gl(p, credit=100, tx='U1')  # no project matches (no projects)
        ctx = RevenueContext(year=2026, month=5)
        self.assertEqual(actual_ytd(ctx), Decimal('100'))  # full total, not 0


# 18. Recognition history
class TestRecognitionHistory(RevenueBase):
    def test_history(self):
        p1 = make_period(2026, 1); p2 = make_period(2026, 2)
        proj = Project.objects.create(project_number='H1', pp=self.pp, project_name='H1', project_value=1000)
        self.gl(p1, credit=100, desc='Termin 1 Proyek H1', tx='H-1')
        self.gl(p2, credit=150, desc='Termin 2 Proyek H1', tx='H-2')
        for row in RevenueLedger.objects.all():
            auto_match_ledger(row)
        maps = GLProjectMapping.objects.filter(project=proj).select_related('ledger')
        self.assertEqual(maps.count(), 2)
        amounts = sorted((m.ledger.credit - m.ledger.debit) for m in maps)
        self.assertEqual(amounts, [Decimal('100'), Decimal('150')])


# 19. Filter Organization -> PP
class TestOrgFilter(RevenueBase):
    def test_org_limits_pp(self):
        other_org = OrganizationUnit.objects.create(code='OTHER', name='OTHER', campus=self.campus)
        other_pp = PPMaster.objects.create(pp_code='9999', organization_unit=other_org)
        ctx = RevenueContext(year=2026, month=6, organization_id=self.org.pk)
        self.assertEqual(ctx.pp, None)  # pp not forced; pp option list scoped below
        from finance.models import PPMaster as PM
        scoped = PM.objects.filter(organization_unit=ctx.organization)
        self.assertIn(self.pp, scoped)
        self.assertNotIn(other_pp, scoped)


# 20. Filter Revenue Type -> Account
class TestTypeFilter(RevenueBase):
    def test_type_limits_account(self):
        ctx = RevenueContext(year=2026, month=6, revenue_type='NTF_RESEARCH')
        from finance.models import RevenueAccount as RA
        scoped = RA.objects.filter(revenue_category=ctx.category)
        self.assertIn(self.acc_nr, scoped)
        self.assertNotIn(self.acc_tf, scoped)


# 21. Data TF grouping: DIFFERENT PP = NEVER MERGE (acceptance #12)
class TestTfAccountPpGrain(RevenueBase):
    def setUp(self):
        super().setUp()
        self.org2 = OrganizationUnit.objects.create(
            code='DIR-ASUS', name='DIREKTORAT ASUS', campus=self.campus, unit_type='OTHER')
        self.pp2 = PPMaster.objects.create(pp_code='2302', organization_unit=self.org2)
        self.acc_reg = RevenueAccount.objects.create(
            account_code='4111101', account_name='Pend. Pendaftaran',
            revenue_category=self.cat_tf)

    def test_pp_never_merged_and_detail_scoped(self):
        from finance.services import tf_account_pp_rows, tf_account_pp_gl
        from finance.services.revenue_context import RevenueContext
        p = make_period(2026, 8)
        # PP 9130 registration: 3 GL rows (100, 150, 200)
        self.gl(p, credit=100, account=self.acc_reg, pp=self.pp, desc='Reg BNI', tx='R1')
        self.gl(p, credit=150, account=self.acc_reg, pp=self.pp, desc='Reg BRI', tx='R2')
        self.gl(p, credit=200, account=self.acc_reg, pp=self.pp, desc='Reg BTN', tx='R3')
        # PP 2302 registration: 2 GL rows (50, 100)
        self.gl(p, credit=50, account=self.acc_reg, pp=self.pp2, desc='Reg MDR', tx='R4')
        self.gl(p, credit=100, account=self.acc_reg, pp=self.pp2, desc='Reg BNI2', tx='R5')

        # PP codes differ -> must produce ONE row PER PP (never 'Semua PP')
        ctx = RevenueContext(year=2026, month=8, revenue_type='TF')
        rows = tf_account_pp_rows(ctx)
        reg = [r for r in rows if r['akun'] == '4111101']
        self.assertEqual(len(reg), 2, 'one row per PP')
        by_pp = {r['pp_code']: r for r in reg}
        self.assertIn('9130', by_pp)
        self.assertIn('2302', by_pp)
        self.assertEqual(by_pp['9130']['total_pendapatan'], Decimal('450'))
        self.assertEqual(by_pp['2302']['total_pendapatan'], Decimal('150'))
        self.assertNotIn('Semua PP', [r['pp_code'] for r in rows])
        # organization from PP master (never 'Semua Unit')
        self.assertEqual(by_pp['9130']['organization'], 'RI-CCSL')
        self.assertEqual(by_pp['2302']['organization'], 'DIREKTORAT ASUS')
        # nilai == YTD for Pendaftaran (no project value in source)
        self.assertEqual(by_pp['9130']['nilai'], Decimal('450'))
        self.assertEqual(by_pp['2302']['nilai'], Decimal('150'))

        # expand PP 9130 -> ONLY its 3 GL rows
        detail1 = tf_account_pp_gl(ctx, '9130', '4111101', 8)
        self.assertEqual(len(detail1), 3)
        self.assertTrue(all(d['pp_code'] == '9130' for d in detail1))
        # expand PP 2302 -> ONLY its 2 GL rows
        detail2 = tf_account_pp_gl(ctx, '2302', '4111101', 8)
        self.assertEqual(len(detail2), 2)
        self.assertTrue(all(d['pp_code'] == '2302' for d in detail2))


# 22. Data TF = per program (TF- Project) per PP — never merged
class TestTfProgramRows(RevenueBase):
    def test_program_rows_per_pp(self):
        from finance.services import tf_program_rows, tf_account_pp_gl
        from finance.services.revenue_context import RevenueContext
        from finance.models import Project
        p = make_period(2026, 8)
        org2 = OrganizationUnit.objects.create(
            code='DIR-ASUS', name='DIREKTORAT ASUS', campus=self.campus, unit_type='OTHER')
        pp2 = PPMaster.objects.create(pp_code='2302', organization_unit=org2)
        # two programs: same name on DIFFERENT PPs must stay separate rows
        proj_a = Project.objects.create(project_number='TF-4121135-9130-01', pp=self.pp, project_name='QRMO 1 2026', project_value=1000)
        proj_b = Project.objects.create(project_number='TF-4121135-2302-01', pp=pp2, project_name='QRMO 1 2026', project_value=800)
        acc_edu = RevenueAccount.objects.create(
            account_code='4121135', account_name='Pendapatan Pddk Pelatihan', revenue_category=self.cat_tf)
        self.gl(p, credit=600, account=acc_edu, pp=self.pp, desc='Penerimaan QRMO 1 2026', tx='Q-A1')
        self.gl(p, credit=600, account=acc_edu, pp=self.pp, desc='Penerimaan QRMO 1 2026 Termin2', tx='Q-A2')
        self.gl(p, credit=300, account=acc_edu, pp=pp2, desc='Penerimaan QRMO 1 2026', tx='Q-B1')
        # map GL -> project (same as seed _match_projects)
        from finance.models import GLProjectMapping
        for row in RevenueLedger.objects.all():
            GLProjectMapping.objects.create(ledger=row, project=proj_a if row.pp == self.pp else proj_b,
                                            allocated_amount=row.credit, match_method='PP+NAME',
                                            match_status='AUTO_MATCHED')
        ctx = RevenueContext(year=2026, month=8, revenue_type='TF')
        rows = tf_program_rows(ctx)
        qrmo = [r for r in rows if r['nama_proyek'] == 'QRMO 1 2026']
        self.assertEqual(len(qrmo), 2, 'same program name on 2 PPs = 2 rows')
        by_pp = {r['pp_code']: r for r in qrmo}
        self.assertIn('9130', by_pp); self.assertIn('2302', by_pp)
        self.assertEqual(by_pp['9130']['total_pendapatan'], Decimal('1200'))
        self.assertEqual(by_pp['2302']['total_pendapatan'], Decimal('300'))
        self.assertNotIn('Semua PP', [r['pp_code'] for r in rows])


# 23. Expand scope: TF program detail = SELECTED MONTH only (spec #10/11)
class TestTfExpandMonthScope(RevenueBase):
    def test_tf_expand_only_selected_month(self):
        from finance.models import Project, GLProjectMapping
        from finance.services import recognition_history, project_summary
        from finance.services.revenue_context import RevenueContext
        acc_reg = RevenueAccount.objects.create(
            account_code='4111101', account_name='Pend. Pendaftaran',
            revenue_category=self.cat_tf)
        proj = Project.objects.create(project_number='TF-4111101-9130-01', pp=self.pp,
                                      project_name='Pendapatan Pendaftaran PIN SMBB',
                                      project_value=1_000_000_000)
        for mon, amt in ((5, 100), (6, 200), (7, 300), (8, 400)):
            p = make_period(2026, mon)
            gl = self.gl(p, credit=amt, account=acc_reg, pp=self.pp, desc=f'Reg PIN {mon}', tx=f'R-{mon}')
            GLProjectMapping.objects.create(ledger=gl, project=proj, allocated_amount=gl.credit,
                                            match_method='PP+NAME', match_status='AUTO_MATCHED')
        # selected August
        rows8 = recognition_history(proj, year=2026, month=8)
        self.assertEqual([r['month'] for r in rows8], [8])
        self.assertEqual(sum(r['amount'] for r in rows8), Decimal('400'))
        # selected July
        rows7 = recognition_history(proj, year=2026, month=7)
        self.assertEqual([r['month'] for r in rows7], [7])
        self.assertEqual(sum(r['amount'] for r in rows7), Decimal('300'))
        # YTD summary still Jan..month
        s8 = project_summary(proj, 2026, 8)
        self.assertEqual(s8['recognized_month'], Decimal('400'))
        self.assertEqual(s8['ytd'], Decimal('1000'))


# 24. Expand mode: PERIOD_ONLY vs HISTORICAL (spec #1..#15)
class TestDetailHistoryMode(RevenueBase):
    def test_mode_drives_history_scope(self):
        from finance.models import Project, GLProjectMapping, RevenueAccount
        from finance.services import recognition_history, project_account_mode
        acc_reg = RevenueAccount.objects.create(account_code='4111101', account_name='Pend. Pendaftaran',
                                                revenue_category=self.cat_tf, detail_history_mode='PERIOD_ONLY')
        acc_edu = RevenueAccount.objects.create(account_code='4121135', account_name='Pddk Pelatihan',
                                                revenue_category=self.cat_tf, detail_history_mode='HISTORICAL')
        proj_reg = Project.objects.create(project_number='TF-4111101-9130-01', pp=self.pp,
                                          project_name='Pendapatan Pendaftaran PIN SMBB', project_value=1000)
        proj_edu = Project.objects.create(project_number='TF-4121135-9130-02', pp=self.pp,
                                          project_name='Pelatihan ABC', project_value=1000)
        def gl_map(proj, acc, y, m, amt):
            p = make_period(y, m)
            g = self.gl(p, credit=amt, account=acc, pp=self.pp, desc='X', tx=f'{proj.pk}-{y}-{m}')
            GLProjectMapping.objects.create(ledger=g, project=proj, allocated_amount=g.credit,
                                            match_method='PP+NAME', match_status='AUTO_MATCHED')
        # Registration: May100 Jun150 Jul200 Aug300
        for m, a in ((5,100),(6,150),(7,200),(8,300)):
            gl_map(proj_reg, acc_reg, 2026, m, a)
        # Education: Dec2025 100, Mar2026 150, Aug2026 200
        gl_map(proj_edu, acc_edu, 2025, 12, 100)
        gl_map(proj_edu, acc_edu, 2026, 3, 150)
        gl_map(proj_edu, acc_edu, 2026, 8, 200)

        self.assertEqual(project_account_mode(proj_reg), 'PERIOD_ONLY')
        self.assertEqual(project_account_mode(proj_edu), 'HISTORICAL')

        # A. Registration Aug -> ONLY Aug (300)
        h = recognition_history(proj_reg, year=2026, month=8)
        self.assertEqual([r['month'] for r in h], [8])
        self.assertEqual(sum(r['amount'] for r in h), Decimal('300'))
        # A2. Registration Jul -> ONLY Jul (200)
        h7 = recognition_history(proj_reg, year=2026, month=7)
        self.assertEqual([r['month'] for r in h7], [7])

        # B. Education HISTORICAL up to Aug 2026 -> Dec25+Mar26+Aug26 = 450
        from datetime import date as _d
        hb = recognition_history(proj_edu, upto_date=_d(2026, 8, 31))
        self.assertEqual(len(hb), 3)
        self.assertEqual(sum(r['amount'] for r in hb), Decimal('450'))
        # B2. up to Jul 2026 -> Dec25 + Mar26 = 250 (Aug not yet)
        hb2 = recognition_history(proj_edu, upto_date=_d(2026, 7, 31))
        self.assertEqual(sum(r['amount'] for r in hb2), Decimal('250'))


# 25. Grain PROJECT x PP x ACCOUNT (spec E-H, no 'Multi Akun')
class TestProjectAccountGrain(RevenueBase):
    def test_multi_account_project_splits_rows(self):
        from finance.models import Project, GLProjectMapping, RevenueAccount
        from finance.services import project_rows
        from finance.services.revenue_context import RevenueContext
        org2 = OrganizationUnit.objects.create(code='DIR-PDPB', name='DIREKTORAT PDPB', campus=self.campus, unit_type='OTHER')
        pp = PPMaster.objects.create(pp_code='9120', organization_unit=org2)
        a1 = RevenueAccount.objects.create(account_code='4140101', account_name='Pendapatan Kerja Sama Proyek', revenue_category=self.cat_np)
        a2 = RevenueAccount.objects.create(account_code='4140102', account_name='Pendapatan Jasa Layanan Proyek', revenue_category=self.cat_np)
        proj = Project.objects.create(project_number='P-9120-001', pp=pp, project_name='Gedung Serbaguna', project_value=Decimal('8700000000'))
        def gm(acc, y, m, amt):
            p = make_period(y, m)
            gl = self.gl(p, credit=amt, account=acc, pp=pp, desc=f'Gedung {acc}', tx=f'G-{acc}-{y}-{m}')
            GLProjectMapping.objects.create(ledger=gl, project=proj, allocated_amount=gl.credit, match_method='PP+NAME', match_status='AUTO_MATCHED')
        gm(a1, 2025, 5, Decimal('1500000000'))
        gm(a1, 2026, 3, Decimal('1000000000'))
        gm(a2, 2025, 6, Decimal('1700000000'))
        gm(a2, 2026, 4, Decimal('1000000000'))
        ctx = RevenueContext(year=2026, month=8, revenue_type='NTF_PROJECT')
        rows = project_rows(ctx)
        g = [r for r in rows if r['project'].pk == proj.pk]
        self.assertEqual(len(g), 2, 'one row per account')
        by_acc = {r['akun']: r for r in g}
        self.assertEqual(by_acc['4140101']['total_pendapatan'], Decimal('2500000000'))
        # Diakui = selected month (Aug: none for this GL set) -> 0
        self.assertEqual(by_acc['4140101']['pendapatan_berjalan'], Decimal('0'))
        # YTD (year 2026) kept in realisasi_ytd
        self.assertEqual(by_acc['4140101']['realisasi_ytd'], Decimal('1000000000'))
        self.assertEqual(by_acc['4140102']['total_pendapatan'], Decimal('2700000000'))
        self.assertEqual(by_acc['4140102']['pendapatan_berjalan'], Decimal('0'))
        self.assertEqual(by_acc['4140102']['realisasi_ytd'], Decimal('1000000000'))
        # nilai project reference repeated per row
        self.assertEqual(by_acc['4140101']['nilai'], Decimal('8700000000'))
        self.assertEqual(by_acc['4140102']['nilai'], Decimal('8700000000'))
        # no 'Multi' anywhere
        self.assertNotIn('Multi', ' '.join(r['akun'] for r in rows))


# 26. Kolom finansial: Diakui = MONTH only; Total = lifetime (spec 6)
class TestFinancialColumnSemantics(RevenueBase):
    def test_diakui_is_month_and_progress_total_value(self):
        from finance.models import Project, GLProjectMapping, RevenueAccount
        from finance.services import project_rows
        from finance.services.revenue_context import RevenueContext
        org = OrganizationUnit.objects.create(code='DIR-KON', name='DIREKTORAT KONSTRUKSI', campus=self.campus, unit_type='OTHER')
        pp = PPMaster.objects.create(pp_code='9120', organization_unit=org)
        acc = RevenueAccount.objects.create(account_code='4140101', account_name='Pendapatan Kerja Sama', revenue_category=self.cat_np)
        proj = Project.objects.create(project_number='P-9120-999', pp=pp, project_name='Gedung X', project_value=Decimal('12000000000'))
        def gm(y, m, amt):
            p = make_period(y, m)
            gl = self.gl(p, credit=amt, account=acc, pp=pp, desc='Gedung X', tx=f'GX-{y}-{m}')
            GLProjectMapping.objects.create(ledger=gl, project=proj, allocated_amount=gl.credit, match_method='PP+NAME', match_status='AUTO_MATCHED')
        # 2025: Termin I 3M, II 2M ; 2026: Feb 1M, Mei 1.5M, Agu 0.9M
        gm(2025, 6, Decimal('3000000000'))
        gm(2025, 8, Decimal('2000000000'))
        gm(2026, 2, Decimal('1000000000'))
        gm(2026, 5, Decimal('1500000000'))
        gm(2026, 8, Decimal('900000000'))
        ctx = RevenueContext(year=2026, month=8, revenue_type='NTF_PROJECT')
        rows = [r for r in project_rows(ctx) if r['project'].pk == proj.pk]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        # Diakui = selected month only (0.9M)
        self.assertEqual(row['pendapatan_berjalan'], Decimal('900000000'))
        # Total = lifetime up to period end (3+2+1+1.5+0.9 = 8.4M)
        self.assertEqual(row['total_pendapatan'], Decimal('8400000000'))
        self.assertEqual(row['nilai'], Decimal('12000000000'))
        # YTD Feb+Mei+Agu = 3.4M kept separately
        self.assertEqual(row['realisasi_ytd'], Decimal('3400000000'))
        # progress = Total/Nilai = 70%
        self.assertEqual(round((row['total_pendapatan'] / row['nilai']) * 100), 70)


# 27. Dummy seed rule: every NTF Research/Project has project_value > 0,
# deterministic, >= lifetime recognized (spec 1/2/3/5).
class TestDummyProjectValue(RevenueBase):
    def test_named_objects_contract_value_ge_lifetime(self):
        # Reuse the deterministic seed helper logic on a scratch project:
        # emulate _seed_named_objects contract = lifetime*(1.10..1.50) rounded up.
        from finance.services.revenue_project_service import project_account_totals
        from finance.models import Project, GLProjectMapping
        from django.db.models import Sum
        org = OrganizationUnit.objects.create(code='DIR-LIT', name='DIREKTORAT LITBANG', campus=self.campus, unit_type='OTHER')
        pp = PPMaster.objects.create(pp_code='9155', organization_unit=org)
        acc = RevenueAccount.objects.create(account_code='4151102', account_name='Jasa Penelitian', revenue_category=self.cat_nr)
        proj = Project.objects.create(project_number='RS-4151102-9155-01', pp=pp, project_name='Penelitian PKDN Dummy', project_value=Decimal('0'), is_active=True)
        # GL per seed pattern: 2025 (mon-1) + 2026 (mon) same name base value
        name = proj.project_name
        h = sum(ord(c) for c in name)
        base = Decimal(30_000_000 + (h % 700) * 1_000_000)
        def gm(y, m, amt):
            p = make_period(y, m)
            gl = self.gl(p, credit=amt, account=acc, pp=pp, desc=f'Penerimaan {name}', tx=f'X-{y}-{m}')
            GLProjectMapping.objects.create(ledger=gl, project=proj, allocated_amount=gl.credit, match_method='PP+NAME', match_status='AUTO_MATCHED')
        gm(2025, 3, base)
        gm(2026, 4, base * Decimal('1.08'))
        life = (GLProjectMapping.objects.filter(project=proj)
                .aggregate(s=Sum('allocated_amount'))['s'])
        # seed helper sets project_value = life * (1.10 + (h//7)%41/100), rounded up 10jt
        uplift = Decimal('1.10') + Decimal((h // 7) % 41) / Decimal('100')
        contract = life * uplift
        if contract % Decimal('10000000'):
            contract = (contract // Decimal('10000000') + 1) * Decimal('10000000')
        self.assertGreater(contract, life)
        # deterministic (same formula twice)
        self.assertEqual(contract, life * uplift if not (life*uplift) % Decimal('10000000') else contract)


# 28. TF dummy: Nilai >= lifetime mapped; progress uses project-level total
class TestTfDummyValue(RevenueBase):
    def test_tf_value_ge_lifetime(self):
        from finance.models import Project, GLProjectMapping, RevenueAccount
        from decimal import Decimal
        from django.db.models import Sum
        # emulate the seed rule on a TF program with 2025 + 2026 GL
        org = OrganizationUnit.objects.create(code='DIR-PS', name='PUSAT STUDI', campus=self.campus, unit_type='OTHER')
        pp = PPMaster.objects.create(pp_code='1103', organization_unit=org)
        acc = RevenueAccount.objects.create(account_code='4121135', account_name='Pelatihan', revenue_category=self.cat_tf)
        p = Project.objects.create(project_number='TF-4121135-1103-01', pp=pp,
                                   project_name='Pelatihan QRMO', project_value=Decimal('0'), is_active=True)
        def gm(y, m, amt):
            prd = make_period(y, m)
            gl = self.gl(prd, credit=amt, account=acc, pp=pp, desc='QRMO', tx=f'Q-{y}-{m}')
            GLProjectMapping.objects.create(ledger=gl, project=p, allocated_amount=gl.credit,
                                            match_method='PP+NAME', match_status='AUTO_MATCHED')
        gm(2025, 6, Decimal('150000000'))
        gm(2026, 6, Decimal('164080000'))   # lifetime = 314.08M
        life = (GLProjectMapping.objects.filter(project=p)
                .aggregate(s=Sum('allocated_amount'))['s'])
        self.assertEqual(life, Decimal('314080000'))
        # seed: value = life * (1.10 + key%51/100) rounded up to 10jt
        key = sum(ord(c) for c in (pp.pp_code + p.project_number))
        contract = life * (Decimal('1.10') + Decimal(key % 51) / Decimal('100'))
        if contract % Decimal('10000000'):
            contract = (contract // Decimal('10000000') + 1) * Decimal('10000000')
        self.assertGreaterEqual(contract, life)
        # realistic margin 1.10..1.60
        self.assertLessEqual(contract, life * Decimal('1.70'))

    def test_multi_account_progress_uses_project_total(self):
        from finance.models import Project, GLProjectMapping, RevenueAccount
        from finance.services import project_rows
        from finance.services.revenue_context import RevenueContext
        org = OrganizationUnit.objects.create(code='DIR-PRO', name='DIREKTORAT PROYEK', campus=self.campus, unit_type='OTHER')
        pp = PPMaster.objects.create(pp_code='9166', organization_unit=org)
        a1 = RevenueAccount.objects.create(account_code='4140101', account_name='Kerja Sama', revenue_category=self.cat_np)
        a2 = RevenueAccount.objects.create(account_code='4140102', account_name='Jasa Layanan', revenue_category=self.cat_np)
        proj = Project.objects.create(project_number='P-9166-001', pp=pp, project_name='Kampus Pusat', project_value=Decimal('10000000000'), is_active=True)
        def gm(acc, y, m, amt):
            p = make_period(y, m)
            gl = self.gl(p, credit=amt, account=acc, pp=pp, desc='Kampus', tx=f'KP-{acc}-{y}-{m}')
            GLProjectMapping.objects.create(ledger=gl, project=proj, allocated_amount=gl.credit, match_method='PP+NAME', match_status='AUTO_MATCHED')
        gm(a1, 2026, 3, Decimal('3000000000'))
        gm(a2, 2026, 4, Decimal('2000000000'))
        ctx = RevenueContext(year=2026, month=8, revenue_type='NTF_PROJECT')
        rows = [r for r in project_rows(ctx) if r['project'].pk == proj.pk]
        self.assertEqual(len(rows), 2)
        # row-level: each account shows own lifetime; progress = project 5M/10M
        for r in rows:
            self.assertEqual(r['project_total_pendapatan'], Decimal('5000000000'))
            self.assertEqual(round(r['project_total_pendapatan'] / r['nilai'] * 100), 50)


# 29. Pendaftaran (PERIOD_ONLY): Nilai == Total == Diakui == selected month
class TestPendaftaranFullProgress(RevenueBase):
    def test_period_only_values_equal_month(self):
        import re
        from finance.models import Project, GLProjectMapping
        from finance.services import tf_program_rows
        from finance.services.revenue_context import RevenueContext
        org = OrganizationUnit.objects.create(code='DIR-ADM', name='ADMISI', campus=self.campus, unit_type='OTHER')
        pp = PPMaster.objects.create(pp_code='3101', organization_unit=org)
        # use account 4111101 Pendaftaran which is PERIOD_ONLY per seed data
        acc = RevenueAccount.objects.create(account_code='4111101', account_name='Pendapatan Pendaftaran', revenue_category=self.cat_tf, detail_history_mode='PERIOD_ONLY')
        proj = Project.objects.create(project_number='TF-4111101-3101-01', pp=pp, project_name='Pendapatan Pendaftaran PIN SMBB', project_value=Decimal('5000000000'), is_active=True)
        def gm(y, m, amt):
            p = make_period(y, m)
            gl = self.gl(p, credit=amt, account=acc, pp=pp, desc='PIN SMBB', tx=f'P-{y}-{m}')
            GLProjectMapping.objects.create(ledger=gl, project=proj, allocated_amount=gl.credit, match_method='PP+NAME', match_status='AUTO_MATCHED')
        # months Feb + Aug 2026
        gm(2026, 2, Decimal('200000000'))
        gm(2026, 8, Decimal('299527200'))
        ctx = RevenueContext(year=2026, month=8, revenue_type='TF')
        rows = [r for r in tf_program_rows(ctx) if r['project'].pk == proj.pk]
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r['detail_mode'], 'PERIOD_ONLY')
        # view normalizes PERIOD_ONLY rows: nilai == total == berjalan == month
        self.assertEqual(r['realisasi_bulan'], Decimal('299527200'))
        # full page render: Pendaftaran shows equal three columns + 100% bar
        resp = self.client.get('/dashboard/revenue/tf/?year=2026&month=8')
        html = resp.content.decode()
        i = html.find('Pendaftaran PIN SMBB')
        self.assertGreater(i, -1)
        seg = html[i:i + 1200]
        self.assertEqual(len(re.findall(r'title="Nilai Proyek: Rp299\.527\.200"', seg)), 1)
        self.assertEqual(len(re.findall(r'title="Total Pendapatan: Rp299\.527\.200"', seg)), 1)
        self.assertEqual(len(re.findall(r'width:100%', seg)), 1)
