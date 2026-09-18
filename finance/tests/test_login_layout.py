"""The login page is the one screen an anonymous visitor sees, so a broken
stylesheet is the most visible failure the app can have. It happened once:
deleting a dead selector from a *shared* selector list took the whole
declaration block with it, leaving

    main.content,
    main.content > div,
    .df-card,
    <blank line>
    .project-table-grid { display: grid; grid-template-columns: 40px 64px ... }

CSS removes comments before parsing, so that is a single valid selector list.
`main.content` and every direct child div silently became the 12-column project
table grid, collapsing the login card into column two. The page still rendered
and every stylesheet still returned 200, so nothing failed loudly.

These tests read the stylesheets the way a browser does.
"""
import re
from pathlib import Path

from django.test import SimpleTestCase

CSS_DIR = Path(__file__).resolve().parents[2] / 'finance' / 'static' / 'finance' / 'css'


def rules(css_text):
    """Yield (selector_list_parts, declarations) for each rule, comments removed.

    Comments are stripped before splitting so the result matches how a browser
    tokenizes the file — which is the whole point: a selector list broken by a
    comment is *not* broken as far as CSS is concerned, it just merges.
    """
    text = re.sub(r'/\*.*?\*/', '', css_text, flags=re.S)
    for match in re.finditer(r'([^{}]+)\{([^{}]*)\}', text):
        selectors = [' '.join(part.split()) for part in match.group(1).split(',')]
        selectors = [s for s in selectors if s]
        yield selectors, ' '.join(match.group(2).split())


def declarations_for(css_text, selector):
    """Declarations that apply to `selector` when it is a member of a rule."""
    found = []
    for selectors, decls in rules(css_text):
        if selector in selectors:
            found.append(decls)
    return found


class LoginStylesheetTests(SimpleTestCase):
    def setUp(self):
        self.dashboard_css = (CSS_DIR / 'dashboard.css').read_text(encoding='utf-8')
        self.manual_css = (CSS_DIR / 'revenue-manual.css').read_text(encoding='utf-8')

    def test_content_is_not_laid_out_as_the_project_table_grid(self):
        """The regression: a stray merge made every content div a table row."""
        for selector in ['main.content', 'main.content > div', '.df-card']:
            with self.subTest(selector=selector):
                decls = declarations_for(self.dashboard_css, selector)
                self.assertTrue(decls, f'{selector} lost its width constraints')
                for decl in decls:
                    self.assertNotIn(
                        'grid-template-columns', decl,
                        f'{selector} inherited the project table grid: {decl}',
                    )
                    self.assertNotEqual(decl, 'display: grid')

    def test_content_keeps_its_width_constraints(self):
        """Deleting a class from this list must not delete the declarations."""
        for selector in ['main.content', 'main.content > div', '.df-card']:
            with self.subTest(selector=selector):
                joined = ' '.join(declarations_for(self.dashboard_css, selector))
                self.assertIn('width: 100%', joined)
                self.assertIn('min-width: 0', joined)

    def test_project_table_grid_is_still_a_grid(self):
        """The other half: the fix must not have stripped the table's layout."""
        decls = declarations_for(self.dashboard_css, '.project-table-grid')
        self.assertTrue(decls)
        self.assertIn('display: grid', ' '.join(decls))

    def test_login_card_selectors_are_defined_and_self_contained(self):
        """The card the login page borrows from the manual-revenue modal."""
        for selector in ['.rm-modal-dialog', '.rm-form', '.rm-field', '.rm-input']:
            with self.subTest(selector=selector):
                decls = declarations_for(self.manual_css, selector)
                self.assertTrue(decls, f'{selector} is missing from revenue-manual.css')
                # A card rule must never pick up the table's column template.
                for decl in decls:
                    self.assertNotIn('grid-template-columns: 40px', decl)

    def test_inputs_fill_their_field(self):
        decls = ' '.join(declarations_for(self.manual_css, '.rm-input'))
        self.assertIn('width: 100%', decls)
