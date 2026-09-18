"""Registrasi Mahasiswa page: quota, registration and BPP tariff analysis.

The page renders server-side on first load (so it works without JS and the
numbers are in the HTML) and the same aggregation is exposed as JSON for the
filter form, which refreshes the cards, chart and table in place.

All aggregation lives in `finance.services.student_registration_service`.
"""
import json

from django.http import JsonResponse
from django.shortcuts import render

from dashboard.views import _assets_head, _fonts_head

from .services import student_registration_service as srs

ACTIVE_TAB = 'registrasi_mahasiswa'


def _scope(request):
    """Read the faculty/program filter from the query string.

    The selection is applied exactly as given. If it matches nothing the page
    shows its empty state, which is honest: silently widening an unknown filter
    to the full dataset would let an operator read unfiltered totals while
    believing they were looking at one faculty.
    """
    return ((request.GET.get('faculty') or '').strip(),
            (request.GET.get('study_program') or '').strip())


def _context(request, faculty, study_program, trend):
    chart_label = srs.filter_labels(faculty, study_program)
    return {
        'assets_head': _assets_head(),
        'fonts_head': _fonts_head(),
        'active': 'dashboard',
        'active_tab': ACTIVE_TAB,
        'faculties': srs.get_faculties(),
        'study_programs': srs.get_study_programs(faculty or None),
        'selected_faculty': faculty,
        'selected_study_program': study_program,
        'trend': trend,
        'chart_label': chart_label,
        # Same payload the JSON endpoint returns, inlined so the first paint
        # needs no extra round trip (and works before the JS runs).
        'trend_json': json.dumps({
            'years': trend['years'],
            'series': trend['series'],
            'summary': trend['summary'],
            'has_data': trend['has_data'],
            'table': trend['table'],
            'chart_label': chart_label,
        }),
    }


def registrasi_mahasiswa(request):
    faculty, study_program = _scope(request)
    trend = srs.get_registration_trend(faculty or None, study_program or None)
    return render(request, 'finance/registrasi_mahasiswa.html',
                  _context(request, faculty, study_program, trend))


def registrasi_mahasiswa_data(request):
    """Aggregated series for the current filter (JSON)."""
    faculty, study_program = _scope(request)
    return JsonResponse(srs.get_registration_trend(faculty or None, study_program or None))


def registrasi_mahasiswa_programs(request):
    """Study programs within a faculty, for the dependent dropdown (JSON)."""
    faculty = (request.GET.get('faculty') or '').strip()
    if faculty and faculty not in srs.get_faculties():
        faculty = ''
    return JsonResponse({'study_programs': srs.get_study_programs(faculty or None)})
