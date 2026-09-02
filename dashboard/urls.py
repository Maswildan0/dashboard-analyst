"""
URL configuration for the dashboard analyst project.

Maps 1:1 to the original Laravel routes:
  GET /                  -> DashboardController@index
  GET /dashboard/data    -> DashboardController@data
  GET /data              -> DashboardController@realisasi
  GET /data/export       -> DashboardController@export

The /build/ prefix serves the Vite build output (same as Laravel's public/
root): the hashed assets referenced by the templates.

When DEBUG=False (e.g. Vercel production) the built-in staticfiles serving is
disabled, so /static/ (the logo) is served directly from public/ here.
"""

from django.conf import settings
from django.http import FileResponse, Http404
from django.urls import include, path, re_path

from . import views


def _serve_file(request, root, path):
    from pathlib import Path
    root = Path(root)
    candidate = (root / path).resolve()
    if not str(candidate).startswith(str(root.resolve())) or not candidate.is_file():
        raise Http404
    return FileResponse(candidate.open('rb'))


def _build_file(request, path):
    """Serve a file from public/build (Vite output)."""
    return _serve_file(request, settings.BASE_DIR / 'public' / 'build', path)


def _static_file(request, path):
    """Serve a file from public/ (static assets like the logo) so the app
    works without collectstatic when DEBUG=False."""
    return _serve_file(request, settings.BASE_DIR / 'public', path)


urlpatterns = [
    # Financial dashboard is the landing page (/) — see finance/urls.py.
    path('', include('finance.urls')),
    # Original dashboard moved under /dashboard/.
    path('dashboard/', views.index, name='dashboard'),
    path('dashboard/data', views.data, name='dashboard-data'),
    path('dashboard/data/table', views.realisasi, name='realisasi'),
    path('dashboard/data/export', views.export, name='realisasi-export'),
    re_path(r'^build/(?P<path>.*)$', _build_file, name='build-assets'),
    re_path(r'^static/(?P<path>.*)$', _static_file, name='static-fallback'),
]
