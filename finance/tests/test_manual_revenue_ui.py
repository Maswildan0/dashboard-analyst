"""UI regression guards for the manual-revenue CRUD integration.

Two defects shipped once and must never return, so both are asserted directly
against the RENDERED HTML:

1. Developer comments reaching the DOM. Django's template tokenizer compiles
   ``tag_re`` = ``({%.*?%}|{{.*?}}|{#.*?#})`` WITHOUT ``re.DOTALL``, so ``.``
   never matches a newline: a ``{# ... #}`` comment spanning more than one line
   is never tokenized and is emitted verbatim as page text. Only the
   ``{% comment %}`` block tag is multi-line safe.

2. Grid cells wrapping to a stray implicit track. The revenue tables are CSS
   grids; every row renders one child per declared track. A child count that
   drifts from ``grid-template-columns`` auto-places the overflow into column 1
   of a new implicit row — which is what produced vertical text in the narrow
   chevron column once the ACTION column was added.

The guards below read the rendered response, so they fail on the real page, not
on a template's source text.
"""
import re
from html.parser import HTMLParser
from urllib.parse import quote

from django.contrib.auth.models import Permission, User
from django.test import override_settings

from finance.tests.test_manual_revenue import ManualRevenueBase

# Every prefix that must never appear as literal page text.
TEMPLATE_LITERALS = [r'\{#', r'#\}', r'\{%', r'%\}', r'\{\{', r'\}\}']

PAGES = {
    'data': '/dashboard/revenue/data/?tahun[]=2026&bulan[]=8',
    'tf': '/dashboard/revenue/tf/?tahun[]=2026&bulan[]=8',
    'research': '/dashboard/revenue/ntf-research/?tahun[]=2026&bulan[]=8',
    'project': '/dashboard/revenue/ntf-project/?tahun[]=2026&bulan[]=8',
}

# Declared grid tracks per page (finance/static/finance/css/dashboard.css).
GRID_TRACKS = {'data': 13, 'tf': 12, 'research': 12, 'project': 12}


class _GridChildCounter(HTMLParser):
    """Direct-child count of every element carrying ``project-table-grid``."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []       # [tag, is_grid]
        self.grids = []       # [(classes, child_count)]
        self.open = []        # indices of grids currently open

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get('class', '')
        is_grid = 'project-table-grid' in cls
        if is_grid:
            self.open.append(len(self.grids))
            self.grids.append([cls, 0])
        elif self.open and self.stack and self.stack[-1][1]:
            self.grids[self.open[-1]][1] += 1
        self.stack.append([tag, is_grid])

    def handle_startendtag(self, tag, attrs):
        if self.open and self.stack and self.stack[-1][1]:
            self.grids[self.open[-1]][1] += 1

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                was_grid = self.stack[i][1]
                self.stack = self.stack[:i]
                if was_grid and self.open:
                    self.open.pop()
                break

    def by_kind(self):
        out = {}
        for cls, n in self.grids:
            kind = ('header' if 'project-table-header' in cls
                    else 'total' if 'project-table-total' in cls
                    else 'row')
            out.setdefault(kind, set()).add(n)
        return out


class ManualRevenueUiRegressionTest(ManualRevenueBase):
    def setUp(self):
        super().setUp()
        # The application is private now, so the regression assertions below
        # run as a signed-in operator rather than an anonymous visitor.
        self.client.force_login(self.editor)
        # A populated table is what the regression is about: with no rows the
        # pages render their empty state and no grid exists to check.
        self.create_manual(project_name='Manual NTF Project', category=self.cat_np,
                           account=self.acc_np)
        self.create_manual(project_name='Manual NTF Research', category=self.cat_nr,
                           account=self.acc_nr)
        self.create_manual(project_name='Manual TF Object', category=self.cat_tf,
                           account=self.acc_tf)

    def test_no_template_literal_reaches_the_dom(self):
        for name, url in PAGES.items():
            with self.subTest(page=name):
                html = self.client.get(url).content.decode()
                for pattern in TEMPLATE_LITERALS:
                    self.assertIsNone(
                        re.search(pattern, html),
                        f'{name}: literal /{pattern}/ leaked into the page')

    def test_no_developer_comment_text_reaches_the_dom(self):
        # Phrases taken verbatim from the comments that leaked before.
        leaked_phrases = [
            'Shared manual-revenue action area',
            'Single hand-off point',
            'Provenance + row actions',
            'existing column template stays untouched',
            'Transaction-level edit form',
            'Each partial owns one responsibility',
        ]
        for name, url in PAGES.items():
            with self.subTest(page=name):
                html = self.client.get(url).content.decode()
                for phrase in leaked_phrases:
                    self.assertNotIn(phrase, html, f'{name}: leaked {phrase!r}')

    def test_grid_children_match_the_declared_tracks(self):
        for name, url in PAGES.items():
            with self.subTest(page=name):
                html = self.client.get(url).content.decode()
                counter = _GridChildCounter()
                counter.feed(html)
                kinds = counter.by_kind()
                expected = {GRID_TRACKS[name]}
                # header, every data row and the grand-total row must agree,
                # otherwise a cell auto-places onto an implicit track.
                self.assertEqual(kinds['header'], expected, f'{name}: header columns')
                self.assertEqual(kinds['total'], expected, f'{name}: grand-total columns')
                self.assertEqual(kinds['row'], expected, f'{name}: data-row columns')

    def test_action_bar_sits_outside_and_before_the_table(self):
        for name, url in PAGES.items():
            with self.subTest(page=name):
                html = self.client.get(url).content.decode()
                bar = html.find('rm-actionbar')
                table = html.find('project-table-scroll-')
                self.assertGreaterEqual(bar, 0, f'{name}: action bar missing')
                self.assertGreater(table, bar, f'{name}: action bar not above the table')

    def test_modals_are_rendered_outside_the_table(self):
        for name, url in PAGES.items():
            with self.subTest(page=name):
                html = self.client.get(url).content.decode()
                table = html.find('project-table-scroll-')
                first_panel = html.find('rev-detail-panel', table)
                region = html[table:first_panel] if first_panel > table else html[table:]
                self.assertNotIn('data-rm-modal', region,
                                 f'{name}: a modal is nested inside the table region')

    def test_recognition_fragment_colspan_matches_its_columns(self):
        project, _ = self.mapped_project('P-9130-900', self.acc_np)
        # Keying a recognition onto an imported project carries no master
        # fields (an imported master is never renamed), so no project_name.
        self.create_manual(project=project, project_name='', amount=1000)
        url = f'/dashboard/revenue/ntf-project/{project.pk}/recognitions/'
        html = self.client.get(
            url, {'year': 2026, 'month': 8},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest').json()['html']
        headers = len(re.findall(r'<th[ >]', html))
        self.assertEqual(headers, 7, 'recognition table column count')
        # Each transaction row carries its own action cell.
        self.assertIn('rev-rec-act', html)
        # Provenance stays a badge, never a fabricated GL voucher.
        self.assertIn('rm-badge-manual', html)

    def test_recognition_fragment_empty_state_colspan(self):
        project, _ = self.mapped_project('P-9130-901', self.acc_np)
        # A period with no recognition rows at all.
        url = f'/dashboard/revenue/ntf-project/{project.pk}/recognitions/'
        html = self.client.get(
            url, {'year': 2025, 'month': 1},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest').json()['html']
        colspans = re.findall(r'colspan="(\d+)"', html)
        headers = len(re.findall(r'<th[ >]', html))
        if colspans:
            for cs in colspans:
                self.assertEqual(int(cs), headers,
                                 'empty-state colspan must match the column count')

    def test_controls_vanish_when_the_user_has_no_permission(self):
        """An unpermitted session must not render the gated controls, and the
        one ungated control must still render.

        This is the defect reported in the field: with an all-false capability
        set "+ Input Manual" and every gated row-menu entry are omitted,
        leaving only "Data Terhapus" — which is ungated. The bootstrap below
        covers that gap, so this test pins the STRICT path by disabling it."""
        with override_settings(REVENUE_PERMISSION_FALLBACK=False):
            self.client.force_login(
                self.user('nobody', []))  # authenticated, zero permissions
            html = self.client.get(PAGES['data']).content.decode()
        self.assertNotIn('data-rm-open="create"', html)
        self.assertIn('Data Terhapus', html)
        self.assertIn('data-can-create="0"', html)
        # The fixture's manual row offers nothing this user may do, so the
        # toggle must be omitted rather than opening an empty panel (§10).
        self.assertIn('rm-badge-manual', html)
        self.assertNotIn('data-rm-rowmenu-toggle', html)

    def test_imported_row_never_renders_an_empty_menu(self):
        """§10: an imported row must always offer its three read/correct
        actions, even for a user who may only read (no write permissions)."""
        self.mapped_project('P-9130-950', self.acc_np)
        self.client.force_login(self.user('reader', ['view_audit']))
        html = self.client.get(PAGES['data']).content.decode()
        # An imported row (GL-backed, not MANUAL) keeps its read/correct menu
        # even for a user with no write permission.
        self.assertIn('data-rm-detail', html)
        self.assertIn('data-rm-history-project', html)
        # and never an edit/delete on imported source
        self.assertNotIn('data-rm-void-project', html)

    def test_superuser_sees_every_gated_control(self):
        from django.contrib.auth.models import User
        boss = User.objects.create_superuser('boss', 'b@x.test', 'pw')
        self.client.force_login(boss)
        html = self.client.get(PAGES['data']).content.decode()
        self.assertIn('data-rm-open="create"', html)
        self.assertIn('data-can-create="1"', html)
        self.assertIn('data-can-void="1"', html)
        self.assertIn('data-can-adjust="1"', html)

    def test_controls_appear_for_a_signed_in_operator_before_roles_exist(self):
        """§4: while NO manual permission is assigned to anybody, a signed-in
        operator still gets the gated controls, so the CRUD is usable before
        roles are finalised. This is the field defect: without it the action
        bar shows only "Data Terhapus"."""
        self._unassign_every_manual_permission()
        self.client.force_login(self.user('fresh', []))
        html = self.client.get(PAGES['data']).content.decode()
        self.assertIn('data-rm-open="create"', html)
        self.assertIn('data-can-create="1"', html)
        self.assertIn('data-can-edit="1"', html)

    def test_anonymous_visitor_never_reaches_the_page_at_all(self):
        """Authentication is never part of the bootstrap, and since the whole
        application is private an anonymous request does not even receive the
        page: it is redirected to the login form (see finance.middleware)."""
        self._unassign_every_manual_permission()
        resp = self.client_class().get(PAGES['data'])
        self.assertEqual(resp.status_code, 302)
        # The fixture URL carries period filters; the path is preserved as-is
        # and only the query string is escaped, so a deep link survives login.
        self.assertEqual(resp.headers['Location'],
                         '/login/?next=' + quote(PAGES['data'], safe='/'))

    def test_bootstrap_switches_itself_off_once_permissions_are_assigned(self):
        """Assigning the operator permissions ends the bootstrap for everyone,
        which is what makes it temporary rather than a permanent bypass."""
        from finance.permissions import ACTION_PERMS, in_bootstrap
        self.assertFalse(in_bootstrap(), 'fixture already assigns permissions')
        html = self.client.get(PAGES['data']).content.decode()
        self.assertIn('data-rm-open="create"', html)  # editor holds create
        self.assertTrue(all(v for v in ACTION_PERMS.values()))

    def test_bootstrap_can_be_disabled_to_exercise_the_strict_path(self):
        self._unassign_every_manual_permission()
        with override_settings(REVENUE_PERMISSION_FALLBACK=False):
            self.client.force_login(self.user('fresh2', []))
            html = self.client.get(PAGES['data']).content.decode()
        self.assertNotIn('data-rm-open="create"', html)
        self.assertIn('data-can-create="0"', html)

    def _unassign_every_manual_permission(self):
        """Put the database back in the 'no roles configured yet' state."""
        from django.contrib.auth.models import Group
        from finance.permissions import ACTION_PERMS
        codenames = [label.split('.', 1)[1] for label in ACTION_PERMS.values()]
        perms = Permission.objects.filter(
            content_type__app_label='finance', codename__in=codenames)
        for user in User.objects.all():
            user.user_permissions.remove(*perms)
        for group in Group.objects.all():
            group.permissions.remove(*perms)

    def test_rows_carry_the_coordinates_the_dialogs_prefill_from(self):
        """The row menus open a dialog on the row's own PP / account. Those
        coordinates are emitted as data attributes; a row without them opens
        the dialog with an empty cascade and the operator cannot save."""
        project, _ = self.mapped_project('P-9130-960', self.acc_np)
        html = self.client.get(PAGES['data']).content.decode()
        self.assertIn('data-rm-type="NTF_PROJECT"', html)
        self.assertIn(f'data-rm-org="{self.org.pk}"', html)
        self.assertIn(f'data-rm-pp="{self.pp.pp_code}"', html)
        self.assertIn(f'data-rm-account="{self.acc_np.account_code}"', html)

    def test_transaction_action_menu_is_permission_gated(self):
        project, _ = self.mapped_project('P-9130-902', self.acc_np)
        entry = self.create_manual(project=project, project_name='', amount=1000)
        url = f'/dashboard/revenue/ntf-project/{project.pk}/recognitions/'
        html = self.client.get(
            url, {'year': 2026, 'month': 8},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest').json()['html']
        self.assertIn(f'data-rm-void-entry="{entry.pk}"', html)

        # A viewer without write rights sees the history but no destructive item.
        self.client.force_login(self.viewer)
        html_viewer = self.client.get(
            url, {'year': 2026, 'month': 8},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest').json()['html']
        self.assertNotIn(f'data-rm-void-entry="{entry.pk}"', html_viewer)
        self.assertNotIn('data-rm-edit-entry-from-history', html_viewer)
