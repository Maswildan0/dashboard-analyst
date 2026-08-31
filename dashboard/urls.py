"""
URL configuration for the dashboard analyst project.

Maps 1:1 to the original Laravel routes:
  GET /                  -> DashboardController@index
  GET /dashboard/data    -> DashboardController@data
  GET /data              -> DashboardController@realisasi
  GET /data/export       -> DashboardController@export

The /build/ prefix serves the Vite build output (same as Laravel's public/
root): the hashed assets referenced by the templates.
"""

from django.conf import settings
from django.http import FileResponse, Http404
from django.urls import path, re_path

from . import views


def _build_file(request, path):
    """Serve a file from public/build, mirroring the original public/build
    URL layout (Vite emits relative 'assets/...' paths there)."""
    from pathlib import Path
    root = settings.BASE_DIR / 'public' / 'build'
    candidate = (root / path).resolve()
    if not str(candidate).startswith(str(root.resolve())) or not candidate.is_file():
        raise Http404
    return FileResponse(candidate.open('rb'))


urlpatterns = [
    path('', views.index, name='dashboard'),
    path('dashboard/data', views.data, name='dashboard-data'),
    path('data', views.realisasi, name='realisasi'),
    path('data/export', views.export, name='realisasi-export'),
    re_path(r'^build/(?P<path>.*)$', _build_file, name='build-assets'),
]
