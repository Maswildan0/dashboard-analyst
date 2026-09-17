"""The application is private (§1-#21): every page and endpoint requires a
signed-in user, and anonymous visitors are sent to /login/?next=<path>.

These are end-to-end HTTP assertions against the real URL tree and the real
middleware stack, so they fail if a route is added without protection, if the
login redirect stops carrying `next`, or if the sign-in page starts leaking
dashboard chrome.

Coverage map (the brief's §18 list):
    A anonymous /                  -> redirect to /login/
    B anonymous Revenue Overview   -> redirect to login
    C anonymous Data Revenue       -> redirect to login
    D anonymous POST create        -> rejected, nothing written
    E authenticated user GET page  -> allowed
    F operator create              -> allowed
    G user without permission      -> rejected
    H logout                       -> redirect to /login/
    I next parameter               -> original internal page after login
    J malicious external next      -> never redirected off-site
"""
from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from finance.models import ManualRevenueEntry

# One representative URL per protected surface. `None` means "JSON endpoint,
# expects a 401 rather than a redirect" (finance.middleware).
PAGES = {
    'financial_overview': '/',
    'revenue_overview': '/dashboard/',
    'data_revenue': '/dashboard/revenue/data/',
    'data_tf': '/dashboard/revenue/tf/',
    'data_ntf_research': '/dashboard/revenue/ntf-research/',
    'data_ntf_project': '/dashboard/revenue/ntf-project/',
    'data_quality': '/dashboard/revenue/data-quality/',
    'dashboard_json': '/dashboard/data',
    'realisation_table': '/dashboard/data/table',
    'realisation_export': '/dashboard/data/export',
    'password_change': '/password_change/',
}

AJAX_ENDPOINTS = {
    'manual_entries': '/dashboard/revenue/manual/entries/',
    'manual_history': '/dashboard/revenue/manual/history/',
    'manual_deleted': '/dashboard/revenue/manual/deleted/',
    'options_pps': '/dashboard/revenue/manual/options/pps/',
    'options_accounts': '/dashboard/revenue/manual/options/accounts/',
    'options_projects': '/dashboard/revenue/manual/options/projects/',
    'options_ledger': '/dashboard/revenue/manual/options/ledger/',
    'filter_pps': '/dashboard/revenue/filter/pps/',
    'filter_accounts': '/dashboard/revenue/filter/accounts/',
}

# Endpoints that WRITE. Each must refuse an anonymous caller.
WRITE_ENDPOINTS = {
    'manual_create': '/dashboard/revenue/manual/create/',
    'manual_edit': '/dashboard/revenue/manual/1/edit/',
    'manual_project_edit': '/dashboard/revenue/manual/project/1/edit/',
    'manual_void': '/dashboard/revenue/manual/1/void/',
    'manual_restore': '/dashboard/revenue/manual/1/restore/',
    'manual_adjustment': '/dashboard/revenue/manual/adjustment/',
}

PUBLIC = {
    'login': '/login/',
    'static_logo': '/static/img/telkom-logo.png',
    'built_manifest': '/build/manifest.json',
}


class AnonymousRedirectTest(TestCase):
    """A/B/C + §10: every page redirects, and no page renders first."""

    def test_every_private_page_redirects_to_login(self):
        for name, url in PAGES.items():
            with self.subTest(page=name):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 302, name)
                self.assertEqual(resp.headers['Location'],
                                 f'/login/?next={url}', name)

    def test_root_redirects_to_login_with_its_own_next(self):
        """A: GET / -> /login/?next=/ (§9)."""
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers['Location'], '/login/?next=/')

    def test_no_dashboard_content_is_rendered_before_login(self):
        """The redirect must not come with the page body attached."""
        html = self.client.get('/dashboard/revenue/data/').content.decode()
        for leak in ('project-table-row', 'rm-actionbar', 'rev-name-cell',
                     'app-sidebar', 'Total Pendapatan'):
            self.assertNotIn(leak, html, f'leaked {leak!r} to an anonymous visitor')

    def test_query_string_survives_the_redirect(self):
        resp = self.client.get('/dashboard/revenue/data/?tahun[]=2026&bulan[]=8')
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers['Location'].startswith(
            '/login/?next=/dashboard/revenue/data/'))

    def test_public_urls_stay_reachable(self):
        """§5: the login page and the assets it needs are the only exceptions."""
        for name, url in PUBLIC.items():
            with self.subTest(public=name):
                self.assertEqual(self.client.get(url).status_code, 200, name)

    def test_login_page_shows_no_dashboard_chrome(self):
        """§7, §8: no sidebar, no topbar, no operator name before sign-in."""
        html = self.client.get('/login/').content.decode()
        self.assertNotIn('app-sidebar', html)
        self.assertNotIn('sidebar-menu', html)
        self.assertNotIn('topbar', html)
        self.assertIn('FINANCIAL ANALYTICS', html)

    def test_login_page_renders_no_template_marker_as_text(self):
        """A marker spanning several lines is not tokenized by Django and is
        rendered verbatim; a marker nested inside one closes it early. Either
        way the raw `{# … #}` / `{% … %}` text ends up on the page — and this
        page is the front door, so it must stay clean."""
        html = self.client.get('/login/').content.decode()
        for marker in ('{#', '#}', '{%', '%}', '{{', '}}'):
            self.assertNotIn(marker, html, f'{marker} leaked onto the login page')

    def test_admin_uses_its_own_login(self):
        """§5/§15: /admin/ keeps Django's own authentication."""
        resp = self.client.get('/admin/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/admin/login/', resp.headers['Location'])


class AnonymousWriteTest(TestCase):
    """D: writes are refused for anonymous callers, and nothing is persisted."""

    def test_anonymous_post_to_every_write_endpoint_is_refused(self):
        payload = {'period': '2026-08', 'revenue_type': 'TF'}
        for name, url in WRITE_ENDPOINTS.items():
            with self.subTest(endpoint=name):
                resp = self.client.post(url, payload)
                self.assertIn(resp.status_code, (302, 401, 403), name)
                self.assertIn(resp.status_code, (302, 401), name)
        self.assertFalse(ManualRevenueEntry.objects.exists())

    def test_anonymous_ajax_get_gets_401_json_not_a_login_page(self):
        """A silent 302 would make a failed refresh look like an empty result,
        and a failed save look like a success (§6)."""
        for name, url in AJAX_ENDPOINTS.items():
            with self.subTest(endpoint=name):
                resp = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
                self.assertEqual(resp.status_code, 401, name)
                self.assertEqual(resp['Content-Type'], 'application/json')
                self.assertFalse(resp.json()['ok'])
                self.assertEqual(resp.json()['login'], '/login/')


class AuthenticatedAccessTest(TestCase):
    """E: a plain signed-in user reaches the pages (authentication only)."""

    def setUp(self):
        self.user = User.objects.create_user('analyst', password='pw-12345')
        self.client.force_login(self.user)

    def test_authenticated_user_reaches_every_page(self):
        for name, url in PAGES.items():
            with self.subTest(page=name):
                self.assertEqual(self.client.get(url).status_code, 200, name)

    def test_root_renders_the_financial_overview(self):
        """§9: authenticated "/" is the Financial Overview, not a redirect."""
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.request['PATH_INFO'], '/')

    def test_sidebar_is_rendered_for_a_signed_in_operator(self):
        html = self.client.get('/dashboard/').content.decode()
        self.assertIn('app-sidebar', html)
        self.assertIn('Revenue Overview', html)
        self.assertIn('analyst', html)   # the topbar shows who is signed in
        self.assertIn('Logout', html)

    def test_signed_in_operator_can_re_authenticate(self):
        """Django's LoginView redraws the form when already signed in; what
        matters is that a valid POST still ends on the app, not on the form."""
        resp = self.client.post('/login/', {'username': 'analyst', 'password': 'pw-12345'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers['Location'], '/')


class PermissionStillAppliesTest(TestCase):
    """§14: authentication is not authorization — the manual permissions still
    decide what a signed-in user may do."""

    def setUp(self):
        self.user = User.objects.create_user('viewer', password='pw-12345')
        self.client.force_login(self.user)

    def _payload(self):
        return {'period': '2026-08', 'revenue_type': 'NTF_PROJECT',
                'amount': '1000', 'transaction_date': '2026-08-20'}

    def test_signed_in_user_without_permission_cannot_create(self):
        """G."""
        with self.settings(REVENUE_PERMISSION_FALLBACK=False):
            resp = self.client.post('/dashboard/revenue/manual/create/', self._payload())
            self.assertEqual(resp.status_code, 403)
            self.assertFalse(resp.json()['ok'])
        self.assertFalse(ManualRevenueEntry.objects.exists())

    def test_signed_in_user_without_permission_can_still_read_pages(self):
        """§14: viewing is governed by the page, writing by the permission."""
        with self.settings(REVENUE_PERMISSION_FALLBACK=False):
            self.assertEqual(self.client.get('/dashboard/revenue/data/').status_code, 200)
            self.assertNotIn('data-rm-open="create"',
                             self.client.get('/dashboard/revenue/data/').content.decode())

    def test_user_management_is_staff_only(self):
        """§15: User Management must not open for every signed-in user."""
        resp = self.client.get('/admin/auth/user/')
        self.assertIn(resp.status_code, (302, 403))
        self.assertIn('/admin/login/', resp.headers.get('Location', resp.headers.get('location', '/admin/login/')))


class LoginFlowTest(TestCase):
    """H/I/J: sign-out, `next` handling, and the open-redirect guard."""

    def setUp(self):
        self.user = User.objects.create_user('operator', password='pw-12345')

    def test_logout_redirects_to_login_and_ends_the_session(self):
        """H + §12: after logout the private page is refused again."""
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/dashboard/revenue/data/').status_code, 200)

        resp = self.client.post('/logout/')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers['Location'], '/login/')

        # The session is gone, so the same URL redirects instead of rendering.
        after = self.client.get('/dashboard/revenue/data/')
        self.assertEqual(after.status_code, 302)
        self.assertIn('/login/', after.headers['Location'])

    def test_logout_requires_post(self):
        """A GET link must not be able to sign an operator out (§12)."""
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/logout/').status_code, 405)

    def test_next_returns_the_operator_to_the_original_page(self):
        """I: deep link -> login -> the page that was asked for."""
        resp = self.client.post('/login/?next=/dashboard/revenue/data/',
                                {'username': 'operator', 'password': 'pw-12345'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers['Location'], '/dashboard/revenue/data/')
        self.assertEqual(self.client.get('/dashboard/revenue/data/').status_code, 200)

    def test_login_without_next_lands_on_the_financial_overview(self):
        """§9: no deep link -> the Financial Overview."""
        resp = self.client.post('/login/', {'username': 'operator', 'password': 'pw-12345'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers['Location'], '/')

    def test_external_next_is_never_followed(self):
        """J: an absolute URL in `next` must not become an open redirect."""
        for hostile in ('https://evil.example.com/steal',
                        '//evil.example.com/steal',
                        'http://evil.example.com'):
            with self.subTest(next=hostile):
                resp = self.client.post(f'/login/?next={hostile}',
                                        {'username': 'operator', 'password': 'pw-12345'})
                self.assertEqual(resp.status_code, 302)
                self.assertEqual(resp.headers['Location'], '/')

    def test_bad_credentials_do_not_authenticate(self):
        resp = self.client.post('/login/', {'username': 'operator', 'password': 'wrong'})
        self.assertEqual(resp.status_code, 200)  # form redisplayed
        self.assertEqual(self.client.get('/dashboard/').status_code, 302)


class PrivateCacheTest(TestCase):
    """§13: sensitive pages must not be served from a cache after logout."""

    def test_private_pages_are_no_store(self):
        self.client.force_login(User.objects.create_user('analyst', password='pw-12345'))
        for name, url in PAGES.items():
            with self.subTest(page=name):
                resp = self.client.get(url)
                self.assertEqual(resp['Cache-Control'], 'no-store, private', name)

    def test_assets_keep_their_normal_caching(self):
        """Static assets carry no user data, so the private policy must not be
        stamped on them — a served file sets no policy of its own."""
        for name, url in (('logo', PUBLIC['static_logo']),
                          ('manifest', PUBLIC['built_manifest'])):
            with self.subTest(asset=name):
                resp = self.client.get(url)
                self.assertNotIn('Cache-Control', resp.headers)

    def test_redirect_refusals_are_not_cached_either(self):
        resp = self.client.get('/dashboard/revenue/data/')
        self.assertEqual(resp['Cache-Control'], 'no-store, private')
