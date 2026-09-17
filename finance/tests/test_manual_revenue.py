"""Manual revenue data management (§54-#61).

Covers the observable contracts of the feature:
  * create lands on the right pages and in the canonical actual exactly once;
  * edit / void / restore move the canonical actual and append audit events;
  * a CLOSED period is refused SERVER-side for every mutation;
  * imported source rows offer no edit/delete path, only an adjustment;
  * the audit trail is append-only (a DELETE event survives a RESTORE);
  * Amount parsing is Decimal-only (NaN/Infinity/garbage rejected).

Amounts are asserted through the SAME readers the pages use, so a regression in
any one page surfaces here.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from finance.models import (
    Campus,
    FinancialDataAuditLog,
    FinancialPeriod,
    GLProjectMapping,
    ManualRevenueEntry,
    OrganizationUnit,
    PPMaster,
    Project,
    RevenueAccount,
    RevenueCategory,
    RevenueLedger,
)
from finance.services import manual_revenue as mr
from finance.services import revenue_project_service as rps
from finance.services import revenue_service as rs
from finance.services.revenue_context import RevenueContext

PAGES = {
    'tf': '/dashboard/revenue/tf/',
    'research': '/dashboard/revenue/ntf-research/',
    'project': '/dashboard/revenue/ntf-project/',
    'data': '/dashboard/revenue/data/',
}


class ManualRevenueBase(TestCase):
    def setUp(self):
        self.campus = Campus.objects.create(code='BDG', name='Bandung')
        self.org = OrganizationUnit.objects.create(
            code='RI-CCSL', name='RI-CCSL', campus=self.campus, unit_type='OTHER')
        self.cat_tf = RevenueCategory.objects.create(code='TF', name='Tuition Fee')
        self.cat_np = RevenueCategory.objects.create(code='NTF_PROJECT', name='NTF Project')
        self.cat_nr = RevenueCategory.objects.create(code='NTF_RESEARCH', name='NTF Research')
        self.pp = PPMaster.objects.create(pp_code='9130', organization_unit=self.org)
        self.acc_np = RevenueAccount.objects.create(
            account_code='4140101', account_name='Kerja Sama', revenue_category=self.cat_np)
        self.acc_nr = RevenueAccount.objects.create(
            account_code='4151102', account_name='Penelitian', revenue_category=self.cat_nr)
        self.acc_tf = RevenueAccount.objects.create(
            account_code='4121135', account_name='Pelatihan', revenue_category=self.cat_tf)

        self.open_period = self.period(2026, 8, closed=False)
        self.closed_period = self.period(2026, 7, closed=True)

        self.editor = self.user('editor', [
            'add_manualrevenueentry', 'change_manualrevenueentry',
            'delete_manualrevenueentry', 'restore_entry', 'create_adjustment',
            'view_audit',
        ])
        self.viewer = self.user('viewer', ['view_audit'])

    # -- helpers ---------------------------------------------------------
    def period(self, year, month, closed=False):
        period, _ = FinancialPeriod.objects.get_or_create(
            year=year, month=month,
            defaults={'period_start': date(year, month, 1),
                      'period_end': date(year, month, 28),
                      'is_closed': closed})
        if period.is_closed != closed:
            period.is_closed = closed
            period.save(update_fields=['is_closed'])
        return period

    def user(self, name, codenames):
        user = User.objects.create_user(username=name, password='x')
        for code in codenames:
            perm = Permission.objects.filter(codename=code).first()
            if perm:
                user.user_permissions.add(perm)
        return User.objects.get(pk=user.pk)

    def gl(self, period, *, credit, account, pp=None, tx='TX'):
        pp = pp or self.pp
        return RevenueLedger.objects.create(
            source_transaction_id=f'{tx}-{RevenueLedger.objects.count() + 1}',
            posting_date=period.period_start, period=period,
            account_code_raw=account.account_code,
            account_name_raw=account.account_name,
            description_raw='imported row',
            pp_code_raw=pp.pp_code, revenue_account=account, pp=pp,
            credit=Decimal(str(credit)), debit=Decimal('0'))

    def mapped_project(self, number, account, pp=None, value=Decimal('1000000000')):
        pp = pp or self.pp
        project = Project.objects.create(
            project_number=number, pp=pp, project_name=f'Imported {number}',
            organization_unit=self.org, campus=self.campus,
            project_value=value, is_active=True)
        ledger = self.gl(self.closed_period, credit=100_000_000, account=account, pp=pp,
                         tx=number)
        GLProjectMapping.objects.create(
            ledger=ledger, project=project, allocated_amount=ledger.credit,
            match_method='PP+NAME', match_status='AUTO_MATCHED')
        return project, ledger

    def create_manual(self, **overrides):
        payload = {
            'period': self.open_period, 'category': self.cat_np,
            'organization': self.org, 'pp': self.pp, 'account': self.acc_np,
            'project': None, 'transaction_date': date(2026, 8, 20),
            'amount': Decimal('125000000'), 'user': self.editor,
            'project_name': 'Manual Object', 'project_value': Decimal('500000000'),
        }
        payload.update(overrides)
        return mr.create_entry(**payload)

    def actual(self, period=None, category=None):
        ctx = RevenueContext(year=2026, month=(period or self.open_period).month,
                             revenue_type=category.code if category else None)
        return rs.actual_ytd(ctx)

    def url(self, name, *args):
        return reverse(f'revenue:manual-{name}', args=args)


# 54. CREATE
class TestCreate(ManualRevenueBase):
    def test_create_lands_on_the_right_pages_once(self):
        entry = self.create_manual()
        ctx = RevenueContext(year=2026, month=8)

        in_project = [r for r in rps.project_rows(ctx) if r['project'].pk == entry.project_id]
        self.assertEqual(len(in_project), 1)
        self.assertEqual(in_project[0]['akun'], '4140101')
        self.assertEqual(in_project[0]['pendapatan_berjalan'], Decimal('125000000.00'))
        # NTF Project only: not on TF, not on NTF Research
        self.assertEqual([r for r in rps.tf_program_rows(ctx)
                          if r['project'].pk == entry.project_id], [])
        self.assertEqual([r for r in rps.research_object_rows(ctx)
                          if r['project'].pk == entry.project_id], [])
        # A manual project carries the category of the account it was keyed
        # under (its 'M-' number has no derivable prefix).
        self.assertEqual(in_project[0]['jenis'], 'NTF_PROJECT')
        research = self.create_manual(
            project_name='Manual Research', category=self.cat_nr,
            account=self.acc_nr, amount=Decimal('5000000'))
        row = [r for r in rps.research_object_rows(ctx)
               if r['project'].pk == research.project_id]
        self.assertEqual(len(row), 1)
        self.assertEqual(row[0]['jenis'], 'NTF_RESEARCH')
        self.assertEqual(row[0]['pendapatan_berjalan'], Decimal('5000000.00'))
        # a manual project is recognisable as such (§14)
        self.assertEqual(entry.project.source_type, 'MANUAL')

        before = rs.actual_ytd(RevenueContext(year=2026, month=8))
        self.create_manual(amount=Decimal('50000000'))
        after = rs.actual_ytd(RevenueContext(year=2026, month=8))
        self.assertEqual(after - before, Decimal('50000000.00'))

        events = [e.action for e in mr.audit_events(entry)]
        self.assertEqual(events, ['CREATE'])


# 55. EDIT
class TestEdit(ManualRevenueBase):
    def test_edit_moves_actual_and_records_before_after(self):
        entry = self.create_manual()
        before_actual = rs.actual_ytd(RevenueContext(year=2026, month=8))

        mr.update_entry(entry, amount=Decimal('175000000'),
                        description='Termin I revisi', user=self.editor)

        after_actual = rs.actual_ytd(RevenueContext(year=2026, month=8))
        self.assertEqual(after_actual - before_actual, Decimal('50000000.00'))

        row = [r for r in rps.project_rows(RevenueContext(year=2026, month=8))
               if r['project'].pk == entry.project_id][0]
        self.assertEqual(row['pendapatan_berjalan'], Decimal('175000000.00'))
        self.assertEqual(row['total_pendapatan'], Decimal('175000000.00'))

        update = [e for e in mr.audit_events(entry) if e.action == 'UPDATE']
        self.assertEqual(len(update), 1)
        self.assertEqual(update[0].old_value['amount'], '125000000.00')
        self.assertEqual(update[0].new_value['amount'], '175000000.00')
        self.assertEqual(update[0].old_value['description'], '')
        self.assertEqual(update[0].new_value['description'], 'Termin I revisi')


# 56. DELETE (soft)
class TestVoid(ManualRevenueBase):
    def test_void_removes_from_active_but_keeps_the_row(self):
        entry = self.create_manual()
        before_actual = rs.actual_ytd(RevenueContext(year=2026, month=8))

        mr.void_entry(entry, reason='Salah input nominal', user=self.editor)

        entry.refresh_from_db()
        self.assertEqual(entry.status, 'VOID')
        self.assertEqual(entry.void_reason, 'Salah input nominal')
        self.assertEqual(entry.voided_by, self.editor)
        self.assertIsNotNone(entry.voided_at)
        # never a physical delete
        self.assertTrue(ManualRevenueEntry.objects.filter(pk=entry.pk).exists())

        after_actual = rs.actual_ytd(RevenueContext(year=2026, month=8))
        self.assertEqual(after_actual, before_actual - Decimal('125000000.00'))

        ctx = RevenueContext(year=2026, month=8)
        self.assertEqual([r for r in rps.project_rows(ctx)
                          if r['project'].pk == entry.project_id], [])

        actions = [e.action for e in mr.audit_events(entry)]
        self.assertEqual(actions, ['CREATE', 'DELETE'])
        deleted = mr.deleted_entries(category_codes=['NTF_PROJECT'])
        self.assertEqual([e.pk for e in deleted], [entry.pk])

    def test_void_requires_a_reason(self):
        entry = self.create_manual()
        with self.assertRaises(mr.ManualRevenueError):
            mr.void_entry(entry, reason='  ', user=self.editor)


# 57. RESTORE
class TestRestore(ManualRevenueBase):
    def test_restore_reactivates_and_keeps_the_delete_event(self):
        entry = self.create_manual()
        full = rs.actual_ytd(RevenueContext(year=2026, month=8))

        mr.void_entry(entry, reason='Double entry', user=self.editor)
        self.assertEqual(rs.actual_ytd(RevenueContext(year=2026, month=8)),
                         full - Decimal('125000000.00'))

        mr.restore_entry(entry, user=self.editor)
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'POSTED')
        self.assertIsNotNone(entry.restored_at)
        self.assertEqual(rs.actual_ytd(RevenueContext(year=2026, month=8)), full)

        actions = [e.action for e in mr.audit_events(entry)]
        self.assertEqual(actions, ['CREATE', 'DELETE', 'RESTORE'])
        # the DELETE event is still there with its reason
        delete_event = [e for e in mr.audit_events(entry) if e.action == 'DELETE'][0]
        self.assertEqual(delete_event.reason, 'Double entry')


# 58. CLOSED period
class TestClosedPeriodLock(ManualRevenueBase):
    def test_closed_period_refuses_every_mutation(self):
        # Create directly into a CLOSED period is refused…
        with self.assertRaises(mr.ManualRevenueError):
            self.create_manual(period=self.closed_period)
        # …and editing/voiding a row whose period was closed afterwards too.
        entry = self.create_manual()
        self.open_period.is_closed = True
        self.open_period.save(update_fields=['is_closed'])

        with self.assertRaises(mr.ManualRevenueError):
            mr.update_entry(entry, amount=Decimal('1'), user=self.editor)
        with self.assertRaises(mr.ManualRevenueError):
            mr.void_entry(entry, reason='Salah PP', user=self.editor)
        entry.status = 'VOID'
        entry.void_reason = 'x'
        entry.save(update_fields=['status', 'void_reason'])
        with self.assertRaises(mr.ManualRevenueError):
            mr.restore_entry(entry, user=self.editor)

    def test_closed_period_is_refused_over_http_not_just_hidden(self):
        entry = self.create_manual()
        self.open_period.is_closed = True
        self.open_period.save(update_fields=['is_closed'])
        self.client.force_login(self.editor)
        resp = self.client.post(self.url('edit', entry.pk), {'amount': '1'})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()['ok'])
        entry.refresh_from_db()
        self.assertEqual(entry.amount, Decimal('125000000.00'))


# 59. IMPORTED source
class TestImportedSource(ManualRevenueBase):
    def test_imported_row_has_no_edit_or_delete_only_adjustment(self):
        project, ledger = self.mapped_project('P-9130-001', self.acc_np)

        # A manual entry cannot be keyed on the wrong account for that project.
        with self.assertRaises(mr.ManualRevenueError) as ctx:
            self.create_manual(project=project, account=self.acc_nr)
        self.assertEqual(str(ctx.exception), mr.MISMATCH_MESSAGE)

        # An adjustment corrects the imported row without touching it.
        original = ledger.credit
        entry = mr.create_entry(
            period=self.open_period, category=self.cat_np, organization=self.org,
            pp=self.pp, account=self.acc_np, project=project,
            transaction_date=date(2026, 8, 25), amount=Decimal('25000000'),
            source_type='ADJUSTMENT', reference_ledger=ledger,
            reason='Koreksi pengakuan', user=self.editor)
        ledger.refresh_from_db()
        self.assertEqual(ledger.credit, original, 'imported amount never overwritten')
        self.assertEqual(entry.reference_ledger_id, ledger.pk)
        self.assertEqual(entry.source_type, 'ADJUSTMENT')
        self.assertEqual([e.action for e in mr.audit_events(entry)], ['ADJUSTMENT'])

        # The imported mapping row is still the project's GL binding.
        self.assertEqual(GLProjectMapping.objects.filter(project=project).count(), 1)

    def test_adjustment_requires_a_reason_and_matching_account(self):
        project, ledger = self.mapped_project('P-9130-002', self.acc_np)
        with self.assertRaises(mr.ManualRevenueError):
            mr.create_entry(
                period=self.open_period, category=self.cat_np, organization=self.org,
                pp=self.pp, account=self.acc_np, project=project,
                transaction_date=date(2026, 8, 25), amount=Decimal('1000'),
                source_type='ADJUSTMENT', reference_ledger=ledger, reason='',
                user=self.editor)
        with self.assertRaises(mr.ManualRevenueError):
            mr.resolve_reference_ledger(ledger.pk, account=self.acc_nr)

    def test_adjustment_never_invents_a_project(self):
        """A correction must target an existing object (§27)."""
        before = Project.objects.count()
        with self.assertRaises(mr.ManualRevenueError) as ctx:
            mr.create_entry(
                period=self.open_period, category=self.cat_np, organization=self.org,
                pp=self.pp, account=self.acc_np, project=None,
                transaction_date=date(2026, 8, 25), amount=Decimal('1000'),
                source_type='ADJUSTMENT', reason='Koreksi pengakuan',
                user=self.editor)
        self.assertEqual(ctx.exception.field, 'project')
        self.assertEqual(Project.objects.count(), before)
        self.assertFalse(ManualRevenueEntry.objects.exists())


# 60. Audit immutability
class TestAuditImmutability(ManualRevenueBase):
    def test_no_endpoint_mutates_the_audit_trail(self):
        entry = self.create_manual()
        mr.update_entry(entry, amount=Decimal('130000000'), user=self.editor)
        before = list(FinancialDataAuditLog.objects.values_list('pk', 'action'))

        self.client.force_login(self.editor)
        for name in ('edit', 'void', 'restore'):
            args = (entry.pk,) if name != 'restore' else (entry.pk,)
            self.client.post(self.url(name, *args), {
                'amount': '1', 'void_reason': 'Salah PP', 'audit_action': 'DELETE',
                'action': 'DELETE', 'audit_id': before[0][0],
            })
        after = list(FinancialDataAuditLog.objects.values_list('pk', 'action'))
        # every original event is still present, unchanged
        for row in before:
            self.assertIn(row, after)


# 61. Reconciliation / no double count
class TestReconciliation(ManualRevenueBase):
    def test_canonical_actual_is_imported_plus_posted_manual(self):
        project, ledger = self.mapped_project('P-9130-003', self.acc_np)
        imported = rs.actual_ytd(RevenueContext(year=2026, month=8))

        manual = self.create_manual(amount=Decimal('40000000'))
        adj = mr.create_entry(
            period=self.open_period, category=self.cat_np, organization=self.org,
            pp=self.pp, account=self.acc_np, project=project,
            transaction_date=date(2026, 8, 26), amount=Decimal('10000000'),
            source_type='ADJUSTMENT', reference_ledger=ledger,
            reason='Koreksi pengakuan', user=self.editor)

        total = rs.actual_ytd(RevenueContext(year=2026, month=8))
        self.assertEqual(total, imported + Decimal('40000000') + Decimal('10000000'))

        # VOID drops out of the canonical total again.
        mr.void_entry(manual, reason='Salah akun', user=self.editor)
        self.assertEqual(rs.actual_ytd(RevenueContext(year=2026, month=8)),
                         imported + Decimal('10000000'))
        self.assertEqual(adj.status, 'POSTED')

    def test_manual_project_never_double_counted_across_page_builders(self):
        # one manual object per category, each on its own project
        self.create_manual(project_name='Manual NP', category=self.cat_np,
                           account=self.acc_np)
        self.create_manual(project_name='Manual NR', category=self.cat_nr,
                           account=self.acc_nr)
        self.create_manual(project_name='Manual TF', category=self.cat_tf,
                           account=self.acc_tf)
        ctx = RevenueContext(year=2026, month=8)
        builders = {
            'tf': rps.tf_program_rows(ctx),
            'research': rps.research_object_rows(ctx),
            'project': rps.project_rows(ctx),
            'service': rps.service_object_rows(ctx),
        }
        seen = {}
        for name, rows in builders.items():
            for row in rows:
                seen.setdefault(row['project'].pk, []).append(name)
        manual_projects = set(Project.objects.filter(source_type='MANUAL')
                              .values_list('pk', flat=True))
        for pk in manual_projects:
            self.assertEqual(len(seen.get(pk, [])), 1,
                             f'manual project {pk} emitted by {seen.get(pk)}')

    def test_page_reports_agree_on_the_same_row(self):
        entry = self.create_manual()
        self.client.force_login(self.editor)
        number = entry.project.project_number
        ntf = self.client.get(PAGES['project'] + f'?tahun[]=2026&bulan[]=8&q={number}').content.decode()
        data = self.client.get(PAGES['data'] + f'?tahun[]=2026&bulan[]=8&q={number}').content.decode()
        self.assertIn('Manual Object', ntf)
        self.assertIn('Manual Object', data)
        # the same money on both pages
        import re
        money_ntf = re.findall(r'Total Pendapatan: (Rp[\d.]+)', ntf)
        money_data = re.findall(r'Total Pendapatan: (Rp[\d.]+)', data)
        self.assertTrue(money_ntf and money_ntf == money_data, (money_ntf, money_data))


# 36. Amount validation
class TestAmountValidation(ManualRevenueBase):
    def test_rejects_non_finite_and_invalid_input(self):
        for bad in ('NaN', 'Infinity', '-Infinity', 'abc', '', '1.234,5x', None):
            with self.assertRaises(mr.ManualRevenueError):
                mr.parse_amount(bad)
        with self.assertRaises(mr.ManualRevenueError):
            mr.parse_amount('0')
        with self.assertRaises(mr.ManualRevenueError):
            mr.parse_amount('1.005')

    def test_accepts_indonesian_and_plain_formats(self):
        self.assertEqual(mr.parse_amount('1.234.567'), Decimal('1234567'))
        self.assertEqual(mr.parse_amount('1.234.567,89'), Decimal('1234567.89'))
        self.assertEqual(mr.parse_amount('1234567,89'), Decimal('1234567.89'))
        self.assertEqual(mr.parse_amount('1234567.89'), Decimal('1234567.89'))
        self.assertEqual(mr.parse_amount('-25000000'), Decimal('-25000000'))
        self.assertEqual(mr.parse_project_value(''), None)
        with self.assertRaises(mr.ManualRevenueError):
            mr.parse_project_value('-1')


# 19 / 33. Authorization
class TestPermissions(ManualRevenueBase):
    def test_write_endpoints_need_auth_and_permission(self):
        entry = self.create_manual()
        # The fixture row is the only entry that may ever exist here: every
        # refused write below must leave the table exactly as it was.
        before = ManualRevenueEntry.objects.count()
        payload = {
            'period': '2026-08', 'revenue_type': 'NTF_PROJECT',
            'organization': str(self.org.pk), 'pp': self.pp.pp_code,
            'revenue_account': self.acc_np.account_code,
            'transaction_date': '2026-08-20', 'amount': '1000',
            'project_name': 'X',
        }
        # Anonymous: the private-application gate intercepts before the view,
        # so the write is refused by redirect rather than by the permission
        # check (finance.middleware). Nothing is committed either way.
        anonymous = self.client.post(self.url('create'), payload)
        self.assertEqual(anonymous.status_code, 302)
        self.assertEqual(anonymous.headers['Location'],
                         f'/login/?next={self.url("create")}')
        self.assertEqual(ManualRevenueEntry.objects.count(), before)

        # An AJAX write is told 401 in JSON so the UI cannot mistake a login
        # page for a successful save.
        ajax = self.client.post(self.url('create'), payload,
                                HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(ajax.status_code, 401)
        self.assertFalse(ajax.json()['ok'])
        self.assertEqual(ManualRevenueEntry.objects.count(), before)

        self.client.force_login(self.viewer)  # view_audit only
        denied = self.client.post(self.url('create'), payload)
        self.assertEqual(denied.status_code, 403)
        denied = self.client.post(self.url('void', entry.pk), {'void_reason': 'Salah PP'})
        self.assertEqual(denied.status_code, 403)
        # read-only history stays available to a signed-in analyst
        self.assertEqual(self.client.get(self.url('history'), {'entry': entry.pk}).status_code, 200)

    def test_csrf_is_required_for_writes(self):
        client = self.client_class(enforce_csrf_checks=True)
        client.force_login(self.editor)
        resp = client.post(self.url('create'), {
            'period': '2026-08', 'revenue_type': 'NTF_PROJECT',
            'organization': str(self.org.pk), 'pp': self.pp.pp_code,
            'revenue_account': self.acc_np.account_code,
            'transaction_date': '2026-08-20', 'amount': '1000',
            'project_name': 'X',
        })
        self.assertEqual(resp.status_code, 403)


# HTTP happy path across the operations (§54-#57 over the wire)
class TestHttpFlow(ManualRevenueBase):
    def test_full_lifecycle_over_http(self):
        client = self.client_class()
        client.force_login(self.editor)

        created = client.post(self.url('create'), {
            'period': '2026-08', 'revenue_type': 'NTF_RESEARCH',
            'organization': str(self.org.pk), 'pp': self.pp.pp_code,
            'revenue_account': self.acc_nr.account_code,
            'transaction_date': '2026-08-20', 'amount': '75000000',
            'project_name': 'Riset Manual', 'project_value': '300000000',
            'description': 'Termin I', 'evidence_number': 'EB-1',
        })
        self.assertEqual(created.status_code, 200)
        entry_id = created.json()['entry_id']

        edited = client.post(self.url('edit', entry_id), {'amount': '90000000'})
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(ManualRevenueEntry.objects.get(pk=entry_id).amount,
                         Decimal('90000000.00'))

        voided = client.post(self.url('void', entry_id), {'void_reason': 'Double entry'})
        self.assertEqual(voided.status_code, 200)
        self.assertEqual(ManualRevenueEntry.objects.get(pk=entry_id).status, 'VOID')
        self.assertTrue(ManualRevenueEntry.objects.filter(pk=entry_id).exists())

        listed = client.get(self.url('deleted'), {'types': 'NTF_RESEARCH'}).json()
        self.assertEqual(listed['count'], 1)
        self.assertIn('data-rm-restore', listed['html'])

        restored = client.post(self.url('restore', entry_id), {})
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(ManualRevenueEntry.objects.get(pk=entry_id).status, 'POSTED')

        history = client.get(self.url('history'), {'project': ManualRevenueEntry.objects.get(pk=entry_id).project_id}).json()
        for action in ('CREATE', 'UPDATE', 'DELETE', 'RESTORE'):
            self.assertIn(action, history['html'])

    def test_void_other_reason_requires_text(self):
        entry = self.create_manual()
        client = self.client_class()
        client.force_login(self.editor)
        resp = client.post(self.url('void', entry.pk), {'void_reason': 'Lainnya'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['field'], 'void_reason_other')
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'POSTED')

    def test_cascade_options_come_from_the_database(self):
        client = self.client_class()
        client.force_login(self.editor)
        pps = client.get(self.url('options-pps'), {'org': self.org.pk}).json()
        self.assertEqual([p['value'] for p in pps], ['9130'])
        accounts = client.get(self.url('options-accounts'), {'type': 'NTF_PROJECT'}).json()
        self.assertEqual([a['value'] for a in accounts], ['4140101'])


# Pages render the shared action area (§1-#4, §62)
class TestActionArea(ManualRevenueBase):
    def test_every_page_offers_the_shared_controls(self):
        client = self.client_class()
        client.force_login(self.editor)
        for key, url in PAGES.items():
            with self.subTest(page=key):
                resp = client.get(url, {'tahun[]': '2026', 'bulan[]': '8'})
                self.assertEqual(resp.status_code, 200)
                html = resp.content.decode()
                self.assertIn('Input Manual', html)
                self.assertIn('Data Terhapus', html)
                self.assertIn('data-rm-modal="create"', html)
                self.assertIn('data-rm-modal="deleted"', html)
                self.assertIn('data-rm-modal="history"', html)
                # the shared partial is used, not a per-page copy
                self.assertIn('revenue-manual.js', html)

    def test_closed_period_disables_input_and_shows_lock(self):
        self.open_period.is_closed = True
        self.open_period.save(update_fields=['is_closed'])
        client = self.client_class()
        client.force_login(self.editor)
        html = client.get(PAGES['project'], {'tahun[]': '2026', 'bulan[]': '8'}).content.decode()
        self.assertIn('CLOSED', html)
        self.assertIn('Periode sudah ditutup.', html)
        self.assertIn('data-period-closed="1"', html)
