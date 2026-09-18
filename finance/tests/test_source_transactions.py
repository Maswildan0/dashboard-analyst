"""Source transaction picker: a project may only reference its OWN GL rows.

One PP carries several projects and they can share a revenue account, so PP +
account is NOT enough to identify a project's transactions: a neighbour
project's row satisfies it just as well. `GLProjectMapping` is the authority,
and these tests pin that every path — the picker query, its search, the option
endpoint, and the write validation — is scoped by it.
"""
from datetime import date
from decimal import Decimal


from finance.models import (
    GLProjectMapping,
    ManualRevenueEntry,
    Project,
    RevenueLedger,
)
from finance.services import manual_revenue as mr
from finance.tests.test_manual_revenue import ManualRevenueBase


class SourceTransactionScopeTest(ManualRevenueBase):
    """A second project sharing the PP + account of the first."""

    def setUp(self):
        super().setUp()
        self.project_a, self.ledger_a = self.mapped_project('P-9130-001', self.acc_np)
        # Same PP and same revenue account, different project.
        self.project_b, self.ledger_b = self.mapped_project('P-9130-003', self.acc_np)
        self.assertEqual(self.project_a.pp_id, self.project_b.pp_id)

    def picked(self, project, **kwargs):
        return list(mr.source_ledger_rows(project.pk, **kwargs))

    # -- scoping (§1, §3, §17) -------------------------------------------
    def test_only_the_projects_own_mappings_are_offered(self):
        a = self.picked(self.project_a)
        self.assertEqual([l.pk for l in a], [self.ledger_a.pk])
        b = self.picked(self.project_b)
        self.assertEqual([l.pk for l in b], [self.ledger_b.pk])
        # The neighbour's transaction is never among them.
        self.assertNotIn(self.ledger_b.pk, [l.pk for l in a])
        self.assertNotIn(self.ledger_a.pk, [l.pk for l in b])

    def test_pp_and_account_filtering_alone_would_leak(self):
        """Documents WHY the mapping is the rule: the old PP + account query
        returns both projects' rows, so it cannot identify one project."""
        by_pp_account = RevenueLedger.objects.filter(
            pp=self.project_a.pp, revenue_account=self.acc_np)
        self.assertEqual(by_pp_account.count(), 2)   # leaks project B
        self.assertEqual(len(self.picked(self.project_a)), 1)

    def test_project_without_mapping_yields_empty_never_the_whole_gl(self):
        orphan = Project.objects.create(
            project_number='P-9130-999', pp=self.pp, project_name='No GL',
            organization_unit=self.org, campus=self.campus,
            project_value=Decimal('1000'), is_active=True)
        self.assertEqual(self.picked(orphan), [])
        # and definitely not every ledger in the database
        self.assertTrue(RevenueLedger.objects.count() > 0)

    def test_unmatched_mapping_does_not_bind_the_project(self):
        """A mapping that no reader trusts cannot make a row offerable."""
        project, ledger = self.mapped_project('P-9130-777', self.acc_np)
        GLProjectMapping.objects.filter(ledger=ledger, project=project).update(
            match_status='UNMATCHED')
        self.assertNotIn(ledger.pk, [l.pk for l in self.picked(project)])

    def test_newest_transaction_comes_first(self):
        """§14: posting date DESC, then id DESC."""
        # Both rows share a period, so only the explicit posting dates decide
        # the order; the earlier one is created LAST so a naive id ordering
        # would put it first.
        later = self.gl(self.open_period, credit=10, account=self.acc_np, tx='LATER')
        later.posting_date = date(2026, 8, 20)
        later.save(update_fields=['posting_date'])
        earlier = self.gl(self.open_period, credit=10, account=self.acc_np, tx='EARLIER')
        earlier.posting_date = date(2026, 8, 1)
        earlier.save(update_fields=['posting_date'])
        for led in (later, earlier):
            GLProjectMapping.objects.create(
                ledger=led, project=self.project_a, allocated_amount=led.credit,
                match_method='PP+NAME', match_status='AUTO_MATCHED')

        rows = self.picked(self.project_a, upto_date=date(2026, 8, 31))
        by_date = [l.pk for l in rows if l.pk in (later.pk, earlier.pk)]
        self.assertEqual(by_date, [later.pk, earlier.pk])

    def test_cutoff_excludes_transactions_after_the_period(self):
        """§13: the project's lifetime stays reachable, nothing later does."""
        future = self.period(2026, 12)
        later = self.gl(future, credit=10, account=self.acc_np, tx='FUTURE')
        GLProjectMapping.objects.create(
            ledger=later, project=self.project_a, allocated_amount=later.credit,
            match_method='PP+NAME', match_status='AUTO_MATCHED')
        rows = self.picked(self.project_a, upto_date=date(2026, 8, 31))
        self.assertNotIn(later.pk, [l.pk for l in rows])


class SourceTransactionSearchTest(ManualRevenueBase):
    def setUp(self):
        super().setUp()
        self.project, self.ledger = self.mapped_project('P-9130-001', self.acc_np)
        self.ledger.voucher_number = 'V-06010'
        self.ledger.document_number = 'DOC-00010'
        self.ledger.description_raw = 'Termin 3 Pengembangan Smart Campus'
        self.ledger.credit = Decimal('913028047.10')
        self.ledger.save()
        self.other, self.other_ledger = self.mapped_project('P-9130-003', self.acc_np)
        self.other_ledger.voucher_number = 'V-09999'
        self.other_ledger.description_raw = 'Revitalisasi Gedung Rektorat'
        self.other_ledger.save()

    def search(self, term):
        return [l.pk for l in mr.source_ledger_rows(self.project.pk, q=term)]

    def test_search_matches_every_visible_column(self):
        self.assertEqual(self.search('V-06010'), [self.ledger.pk])
        self.assertEqual(self.search('DOC-00010'), [self.ledger.pk])
        self.assertEqual(self.search('Termin 3'), [self.ledger.pk])
        self.assertEqual(self.search('913028047'), [self.ledger.pk])

    def test_search_is_case_insensitive(self):
        self.assertEqual(self.search('termin 3'), [self.ledger.pk])
        self.assertEqual(self.search('v-06010'), [self.ledger.pk])

    def test_search_never_reaches_another_project(self):
        """The neighbour's voucher must not surface in this project's search."""
        self.assertEqual(self.search('V-09999'), [])
        self.assertEqual(self.search('Revitalisasi'), [])

    def test_empty_search_returns_the_project_scope(self):
        self.assertEqual(self.search(''), [self.ledger.pk])


class SourceTransactionEndpointTest(ManualRevenueBase):
    """The picker endpoint and the write validation (§15, §16, §17)."""

    URL = '/dashboard/revenue/manual/options/ledger/'

    def setUp(self):
        super().setUp()
        self.client.force_login(self.editor)
        self.project_a, self.ledger_a = self.mapped_project('P-9130-001', self.acc_np)
        self.project_b, self.ledger_b = self.mapped_project('P-9130-003', self.acc_np)

    def options(self, **params):
        resp = self.client.get(self.URL, params)
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_endpoint_returns_only_the_selected_projects_transactions(self):
        a = self.options(project=self.project_a.pk)
        self.assertEqual([o['value'] for o in a], [self.ledger_a.pk])
        b = self.options(project=self.project_b.pk)
        self.assertEqual([o['value'] for o in b], [self.ledger_b.pk])

    def test_options_are_informative_not_bare_ids(self):
        """§4: the operator sees date, voucher, document, description, amount."""
        option = self.options(project=self.project_a.pk)[0]
        for key in ('value', 'date', 'date_text', 'voucher', 'document',
                    'description', 'amount', 'amount_text', 'label'):
            self.assertIn(key, option)
        self.assertTrue(option['date_text'])
        self.assertTrue(option['amount_text'].startswith('Rp'))
        self.assertNotEqual(str(option['value']), option['label'])

    def test_missing_project_returns_nothing(self):
        self.assertEqual(self.options(), [])

    def test_unknown_project_returns_nothing(self):
        self.assertEqual(self.options(project=999999), [])

    def test_search_term_narrows_the_response(self):
        self.ledger_a.voucher_number = 'V-06010'
        self.ledger_a.save()
        self.assertEqual(
            [o['value'] for o in self.options(project=self.project_a.pk, q='V-06010')],
            [self.ledger_a.pk])
        self.assertEqual(self.options(project=self.project_a.pk, q='V-09999'), [])

    def test_endpoint_requires_authentication(self):
        """§16: the picker is as private as the rest of the application."""
        self.assertEqual(self.client_class().get(self.URL).status_code, 302)


class CrossProjectAdjustmentTest(ManualRevenueBase):
    """§16, §17: a correction may only reference its own project's source."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.editor)
        self.project_a, self.ledger_a = self.mapped_project('P-9130-001', self.acc_np)
        self.project_b, self.ledger_b = self.mapped_project('P-9130-003', self.acc_np)

    def payload(self, project, ledger):
        return {
            'period': str(self.open_period), 'revenue_type': 'NTF_PROJECT',
            'organization': str(self.org.pk), 'pp': self.pp.pp_code,
            'revenue_account': self.acc_np.account_code, 'project': project.pk,
            'reference_ledger': ledger.pk, 'transaction_date': '2026-08-25',
            'amount': '25000000', 'reason': 'Koreksi pengakuan',
        }

    def test_service_rejects_a_ledger_from_another_project(self):
        with self.assertRaises(mr.ManualRevenueError) as ctx:
            mr.resolve_reference_ledger(
                self.ledger_b.pk, account=self.acc_np, project=self.project_a)
        self.assertEqual(str(ctx.exception), mr.SOURCE_NOT_MAPPED_MESSAGE)
        self.assertEqual(ctx.exception.field, 'reference')

    def test_service_accepts_the_projects_own_ledger(self):
        ledger = mr.resolve_reference_ledger(
            self.ledger_a.pk, account=self.acc_np, project=self.project_a)
        self.assertEqual(ledger.pk, self.ledger_a.pk)

    def test_endpoint_rejects_a_cross_project_reference(self):
        resp = self.client.post('/dashboard/revenue/manual/adjustment/',
                                self.payload(self.project_a, self.ledger_b))
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()['ok'])
        self.assertEqual(resp.json()['message'], mr.SOURCE_NOT_MAPPED_MESSAGE)
        self.assertFalse(ManualRevenueEntry.objects.exists())
        # The imported source is untouched by the refused attempt.
        self.ledger_b.refresh_from_db()
        self.assertEqual(self.ledger_b.credit, Decimal('100000000'))

    def test_endpoint_accepts_the_matching_pair(self):
        resp = self.client.post('/dashboard/revenue/manual/adjustment/',
                                self.payload(self.project_a, self.ledger_a))
        self.assertEqual(resp.status_code, 200)
        entry = ManualRevenueEntry.objects.get(pk=resp.json()['entry_id'])
        self.assertEqual(entry.reference_ledger_id, self.ledger_a.pk)
        self.assertEqual(entry.project_id, self.project_a.pk)

    def test_pp_and_account_alone_would_have_allowed_the_cross_project_write(self):
        """The reason the check is needed: both rows share PP and account, so
        every PP/account-based guard passes for the wrong project."""
        self.assertEqual(self.ledger_a.pp_id, self.ledger_b.pp_id)
        self.assertEqual(self.ledger_a.revenue_account_id,
                         self.ledger_b.revenue_account_id)
        self.assertFalse(GLProjectMapping.objects.filter(
            project=self.project_a, ledger=self.ledger_b).exists())
