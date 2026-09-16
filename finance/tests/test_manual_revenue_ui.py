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

from django.contrib.auth.models import Permission, User
from django.test import TestCase

from finance.services import manual_revenue as mr
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
