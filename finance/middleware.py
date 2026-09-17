"""Make the whole dashboard private (§1-#21).

Every page and JSON endpoint of this application exposes revenue figures, so
anonymous access is denied unless a route is explicitly exempt. Enforcement
lives in ONE place — Django's own `LoginRequiredMiddleware`, wired in
`settings.MIDDLEWARE` — instead of one decorator per view: a view added later is
private unless somebody deliberately exempts it.

Why the middleware rather than an allowlist of my own:

* it reads the `login_required` attribute carried by each view, so it is secure
  by default while still honouring the standard opt-outs;
* `django.contrib.auth.urls` (login / logout / password reset) and the admin
  login are already marked `login_not_required` by Django itself, which is
  exactly the public surface the app needs — no patch, no duplication;
* its redirect resolves the target through `url_has_allowed_host_and_scheme`,
  so a crafted `?next=` can never point off-site (§11).

The one thing it does not cover is JSON: `redirect_to_login` sends a 302 to the
login page, `fetch` follows it silently, and the caller's `res.json()` then
fails with a generic error — worse, a write POST would look like a *successful*
save because an HTML body yields an empty payload. `AjaxLoginRequiredMiddleware`
answers those callers with 401 and a `login` URL they can act on.
"""
from django.conf import settings
from django.contrib.auth.middleware import LoginRequiredMiddleware
from django.http import JsonResponse

# Set by the dashboard's own JS on every fetch(); see login_required_response.
AJAX_HEADER = 'X-Requested-With'
AJAX_HEADER_VALUE = 'XMLHttpRequest'


def login_url(request):
    """settings.LOGIN_URL prefixed by whatever path this app is mounted on.

    Under `python manage.py runserver` the prefix is empty, but a deployment
    that mounts the app below the domain root would otherwise send the browser
    to the wrong path.
    """
    prefix = (getattr(request, 'script_prefix', '') or '/').rstrip('/')
    return prefix + str(settings.LOGIN_URL)


def is_ajax(request):
    """True when the caller expects a JSON body rather than a page."""
    return request.headers.get(AJAX_HEADER) == AJAX_HEADER_VALUE


class AjaxLoginRequiredMiddleware(LoginRequiredMiddleware):
    """`LoginRequiredMiddleware`, but AJAX callers are told 401, not redirected.

    JSON endpoints share the URL tree with the pages (and with the session
    cookie), so they must answer in JSON rather than HTML: a client that gets a
    login page back would report the wrong outcome for a failed write.
    """

    def handle_no_permission(self, request, view_func):
        if is_ajax(request):
            return JsonResponse(
                {'ok': False, 'message': 'Sesi berakhir. Silakan masuk kembali.',
                 'login': login_url(request)},
                status=401)
        return super().handle_no_permission(request, view_func)
