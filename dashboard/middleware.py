"""Keep private pages out of browser and proxy caches (§12, §13).

Every page here shows financial figures behind a session, so a response must
not be reused after sign-out. Without a policy the browser can serve a cached
page on the Back button after logout: the session is gone, yet the sensitive
markup is still on screen and the server was never asked.

`process_response` stamps `Cache-Control: no-store, private` on application
responses. Two things are deliberately left alone:

* **Assets.** The static/build routes of ``dashboard.urls`` must keep normal
  caching or the dashboard gets slow, and they carry no user data.
* **A policy the view set itself.** ``setdefault`` only fills the header in
  when it is absent, so a view that already decided (a download, a streamed
  response, Django's own ``never_cache``) keeps its own policy.

That second point is why there is no exemption list for the admin: it is
sensitive too, and Django's ``never_cache`` already sets a stricter policy that
``setdefault`` will not overwrite.
"""
from django.conf import settings

CACHE_CONTROL = 'Cache-Control'
NO_STORE = 'no-store, private'


def _public_prefixes():
    """Path prefixes for served assets — never given a private cache policy."""
    return tuple(p for p in (settings.STATIC_URL, '/build/') if p)


class PrivateCacheMiddleware:
    """Stamp a no-store policy on private application responses."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.public_prefixes = _public_prefixes()

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path.startswith(self.public_prefixes):
            response.setdefault(CACHE_CONTROL, NO_STORE)
        return response
