"""Views for the dashboard analyst app.

Ported 1:1 from the original Laravel DashboardController: identical filter
allowlists, deterministic seeded payloads, mock realisasi row set, CSV
export, and the same query-string contract (including `tahun[0]=...` style
array params produced by the Laravel pagination links, plus the `tahun[]`
form style).
"""

import csv
import json
import re
import zlib
from datetime import datetime
from pathlib import Path

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render

from .data import MONTHS, OPTIONS, realisasi_dataset

# Sortable columns on the Data Realisasi table (key -> display name).
SORTABLE = ['tahun', 'bulan', 'unit', 'noPP', 'kodePP', 'direktorat', 'nama', 'nilai', 'totalPendapatan', 'pendapatanBerjalan']

BUILD_DIR = Path(__file__).resolve().parent.parent / 'public' / 'build'

# Inter webfont weights emitted by the laravel-vite-plugin fonts bunny() step.
_FONT_WEIGHTS = [(400, 'C38fXH4l'), (500, 'Cerq10X2'), (600, 'LgqL8muc'), (700, 'Yt3aPRUw'), (800, 'BYj_oED-')]

_FONT_FACE_TEMPLATE = """@font-face {{
  font-family: "Inter";
  font-style: normal;
  font-weight: {weight};
  font-display: swap;
  src: url("/build/assets/inter-{weight}-normal-{hash}.woff2") format("woff2"), url("/build/assets/inter-{weight}-normal-{hash}.woff") format("woff");
  unicode-range: U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD;
}}"""


# Stable hashed filenames from the committed Vite build (public/build). Kept
# hardcoded so the asset tags render even when the manifest file is not on
# the Lambda filesystem (Vercel serves public/** as CDN static files).
_CSS_FILE = 'assets/styles-Czl0HPHo.css'
_JS_FILE = 'assets/app-DHGGzB1U.js'


def _asset_url(name):
    """Resolve an entry name to its /build/ URL from the Vite manifest,
    falling back to the known stable hashed files."""
    try:
        manifest = BUILD_DIR / 'manifest.json'
        entry = json.loads(manifest.read_text(encoding='utf-8')).get(name)
        if entry:
            return f"/build/{entry['file']}"
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if name == 'resources/css/app.css':
        return f'/build/{_CSS_FILE}'
    if name == 'resources/js/app.js':
        return f'/build/{_JS_FILE}'
    return ''


def _fonts_head():
    preloads = '\n'.join(
        f'<link rel="preload" as="font" href="/build/assets/inter-{w}-normal-{h}.woff2" type="font/woff2" crossorigin="anonymous" />'
        for w, h in _FONT_WEIGHTS
    )
    faces = '\n'.join(_FONT_FACE_TEMPLATE.format(weight=w, hash=h) for w, h in _FONT_WEIGHTS)
    return (f'{preloads}\n<style>\n{faces}\n:root {{\n  --font-inter: "Inter";\n}}\n\n.font-inter {{\n  font-family: var(--font-inter);\n}}\n</style>')


def _assets_head():
    css = _asset_url('resources/css/app.css')
    js = _asset_url('resources/js/app.js')
    head = ''
    if css:
        head += f'<link rel="preload" as="style" href="{css}" />'
    if js:
        head += f'<link rel="modulepreload" as="script" href="{js}" />'
    if css:
        head += f'<link rel="stylesheet" href="{css}" />'
    if js:
        head += f'<script type="module" src="{js}"></script>'
    return head


def _multivalue(request, key):
    """Read a possibly-multi-valued query param.

    The original Laravel links encode arrays as `tahun[0]=2025&tahun[1]=2026`,
    the forms as `tahun[]=...`, and single values as `tahun=2025`; collect
    every style the way Laravel's `$request->input()` would.
    """
    values = []
    if key in request.GET:
        values.extend(request.GET.getlist(key))
    if f'{key}[]' in request.GET:
        values.extend(request.GET.getlist(f'{key}[]'))
    for k in request.GET:
        m = re.match(rf'^{re.escape(key)}\[\d+\]$', k)
        if m:
            values.extend(request.GET.getlist(k))
    return values


def _realisasi_filters(request):
    """Read and validate the realisasi drill-through parameters against the
    allowlists; unknown values silently fall back to the defaults."""
    bulan_in = request.GET.get('bulan')
    try:
        triwulan_in = int(request.GET.get('triwulan', '0'))
    except (TypeError, ValueError):
        triwulan_in = 0
    quarter = triwulan_in if 1 <= triwulan_in <= 4 else None

    if quarter is not None:
        bulan = MONTHS[(quarter - 1) * 3]
    elif bulan_in is not None and bulan_in in MONTHS:
        bulan = bulan_in
    else:
        bulan = MONTHS[0]

    tahun_in = request.GET.get('tahun')
    try:
        tahun = int(tahun_in)
    except (TypeError, ValueError):
        tahun = 2025
    if tahun not in OPTIONS['tahun']:
        tahun = 2025

    tipe = request.GET.get('tipe')
    if tipe not in OPTIONS['tipe']:
        tipe = 'Semua'

    return {'tahun': tahun, 'bulan': bulan, 'triwulan': quarter, 'tipe': tipe}


def _dashboard_filters(request):
    """Read and validate the dashboard filter parameters against the same
    allowlists used for the drill-through."""
    tipe = request.GET.get('tipe')
    if tipe not in OPTIONS['tipe']:
        tipe = 'Semua'
    direktorat = request.GET.get('direktorat')
    if direktorat not in OPTIONS['direktorat']:
        direktorat = 'Semua'
    kode_pp = request.GET.get('kode_pp')
    if kode_pp not in OPTIONS['kodePP']:
        kode_pp = 'Semua'
    tahun_in = request.GET.get('tahun')
    if tahun_in == 'Semua':
        tahun = 'Semua'
    else:
        try:
            tahun_int = int(tahun_in)
        except (TypeError, ValueError):
            tahun_int = None
        tahun = tahun_int if tahun_int in OPTIONS['tahun'] else 'Semua'
    return {'tipe': tipe, 'direktorat': direktorat, 'kodePP': kode_pp, 'tahun': tahun}


def _capaian_color(pct: int) -> str:
    """Capaian badge color, 4 tiers (shared with the table progress bar)."""
    if pct < 50:
        return '#FF383C'
    if pct < 70:
        return '#FACC15'
    if pct < 80:
        return '#FF8D28'
    return '#10B981'


def _build_payload(tipe: str, direktorat: str, kode_pp: str, tahun):
    """Build the full dashboard payload for a filter combination, matching
    the original PHP output value-for-value (crc32-seeded LCG included)."""
    if tahun == 'Semua':
        years = OPTIONS['tahun']
        acc = _build_payload(tipe, direktorat, kode_pp, years[0])
        for y in years[1:]:
            p = _build_payload(tipe, direktorat, kode_pp, y)
            for k in range(len(acc['kpis'])):
                acc['kpis'][k]['value'] += p['kpis'][k]['value']
            for chart in ('chartA', 'chartD'):
                for key, series in acc[chart].items():
                    if isinstance(series, list) and key != 'bulan':
                        for idx in range(len(series)):
                            acc[chart][key][idx] = acc[chart][key][idx] + p[chart][key][idx]
            for k in range(len(acc['chartB']['pie'])):
                acc['chartB']['pie'][k]['value'] += p['chartB']['pie'][k]['value']
        rka_series = acc['chartA']['rka']
        rel_series = acc['chartA']['realisasi']
        acc['kpis'][0]['capaian'][0] = f"{int(round(sum(rel_series) / sum(rka_series) * 100))}% Capaian"
        acc['kpis'][2]['capaian'][0] = f"{int(round(rel_series[7] / max(1, rka_series[7]) * 100))}% Capaian"
        for item in acc['chartB']['items']:
            item['pct'] = min(120, int(round(item['realisasi'] / max(1, item['rka']) * 100)))
        for i in range(len(acc['chartD']['capaian'])):
            acc['chartD']['capaian'][i] = int(round(rel_series[i] / max(1, rka_series[i]) * 100))
        acc['kpis'][0]['title'] = 'Total Realisasi Semua Tahun'
        acc['kpis'][1]['title'] = 'Target RKA Semua Tahun'
        return acc

    # Stable seed from the filter combination. PHP's crc32() is a signed
    # 32-bit int, but the LCG masks to 31 bits immediately, so the unsigned
    # value matches the PHP sequence exactly.
    seed = zlib.crc32(f'{tipe}|{direktorat}|{kode_pp}|{tahun}'.encode('utf-8')) & 0xFFFFFFFF

    def rand(min_v, max_v):
        nonlocal seed
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        return min_v + (seed % (max_v - min_v + 1))

    bulan = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agt', 'Sep', 'Okt', 'Nov', 'Des']
    rka = [96, 96, 92, 92, 96, 96, 92, 92, 94, 94, 96, 96]

    realisasi = [rand(70, 100) for _ in range(12)]

    sum_realisasi = sum(realisasi[:8])
    sum_rka = sum(rka) * 1_000_000
    total_realisasi = sum_realisasi * 1_000_000
    target_rka = sum_rka
    realisasi_bulan = realisasi[7] * 1_000_000
    target_rka_bulan = rka[7] * 1_000_000

    capaian_total = int(round(sum_realisasi / sum(rka) * 100))
    capaian_bulan = int(round(realisasi[7] / rka[7] * 100))

    q, q_r, q_rka = [], [], []
    for a, b in ((0, 2), (3, 5), (6, 8), (9, 11)):
        rel = sum(realisasi[a:b + 1])
        rka_s = sum(rka[a:b + 1])
        q.append(min(120, int(round(rel / rka_s * 100))))
        q_r.append(rel)
        q_rka.append(rka_s)

    tahun_lalu, tahun_sekarang, capaian_bulanan = [], [], []
    for i in range(12):
        tahun_sekarang.append(realisasi[i])
        spike = rand(340, 420) if i == 5 else rand(60, 110)
        tahun_lalu.append(spike)
        capaian_bulanan.append(int(round(realisasi[i] / max(1, rka[i]) * 100)))

    return {
        'kpis': [
            {'title': f'Total Realisasi Tahun {tahun}', 'value': total_realisasi, 'icon': 'wallet', 'accent': '#EB3237', 'iconBg': '#ECFDF5', 'iconColor': '#EB3237', 'capaian': [f'{capaian_total}% Capaian', _capaian_color(capaian_total)], 'period': 'tahun'},
            {'title': f'Target RKA Tahun {tahun}', 'value': target_rka, 'icon': 'folder', 'accent': '#5F5F60', 'iconBg': '#EFF6FF', 'iconColor': '#5F5F60', 'capaian': None, 'period': 'tahun'},
            {'title': 'Realisasi Bulan Agustus', 'value': realisasi_bulan, 'icon': 'wallet', 'accent': '#EB3237', 'iconBg': '#ECFDF5', 'iconColor': '#EB3237', 'capaian': [f'{capaian_bulan}% Capaian', _capaian_color(capaian_bulan)], 'period': 'agustus'},
            {'title': 'Target RKA Bulan Agustus', 'value': target_rka_bulan, 'icon': 'folder', 'accent': '#5F5F60', 'iconBg': '#EFF6FF', 'iconColor': '#5F5F60', 'capaian': None, 'period': 'tahun'},
        ],
        'chartA': {'bulan': bulan, 'rka': rka, 'realisasi': realisasi},
        'chartB': {
            'type': 'pie' if tipe == 'Semua' else 'bars',
            'items': [
                {'label': 'TW I',   'pct': q[0], 'realisasi': q_r[0], 'rka': q_rka[0]},
                {'label': 'TW II',  'pct': q[1], 'realisasi': q_r[1], 'rka': q_rka[1]},
                {'label': 'TW III', 'pct': q[2], 'realisasi': q_r[2], 'rka': q_rka[2]},
                {'label': 'TW IV',  'pct': q[3], 'realisasi': q_r[3], 'rka': q_rka[3]},
            ],
            'note': '',
            'pie': [
                {'label': 'NTF', 'value': int(round(sum_realisasi * 0.58)), 'color': '#EB3237'},
                {'label': 'TF',  'value': int(round(sum_realisasi * 0.42)), 'color': '#5F5F60'},
            ],
        },
        'chartD': {'bulan': bulan, 'tahunLalu': tahun_lalu, 'tahunSekarang': tahun_sekarang, 'capaian': capaian_bulanan},
    }


def index(request):
    f = _dashboard_filters(request)
    return render(request, 'dashboard.html', {
        'options': OPTIONS,
        'filters': f,
        'payload': _build_payload(f['tipe'], f['direktorat'], f['kodePP'], f['tahun']),
        'payload_json': json.dumps(_build_payload(f['tipe'], f['direktorat'], f['kodePP'], f['tahun'])),
        'fonts_head': _fonts_head(),
        'assets_head': _assets_head(),
        'active': 'dashboard',
    })


def data(request):
    f = _dashboard_filters(request)
    return JsonResponse(_build_payload(f['tipe'], f['direktorat'], f['kodePP'], f['tahun']))


def _distinct_values(rows, key):
    return sorted({r[key] for r in rows})


def _multi_filter(request, key, allowlist):
    """Read a multi-select request param (array or single value) and keep only
    values present in the allowlist, preserving order and dropping unknowns.
    'Semua' clears the group."""
    values = _multivalue(request, key)
    values = [v for v in values if v != 'Semua']
    return [v for v in values if v in allowlist]


def _realisasi_rows(request):
    filters = _realisasi_filters(request)

    # Multi-select years: rows exist for each selected year. "Semua" means
    # every year. Empty selection falls back to the single validated year.
    tahun_in = _multivalue(request, 'tahun')
    all_years = 'Semua' in tahun_in
    tahun_values = []
    for t in tahun_in:
        try:
            t_int = int(t)
        except (TypeError, ValueError):
            continue
        if t_int in OPTIONS['tahun'] and t_int not in tahun_values:
            tahun_values.append(t_int)
    tahun_options = OPTIONS['tahun']
    if all_years:
        tahun_values = ['Semua']
    elif not tahun_values:
        tahun_values = [filters['tahun']]
    dataset_years = tahun_options if tahun_values == ['Semua'] else tahun_values

    rows = []
    for t in dataset_years:
        rows.extend(realisasi_dataset(t))

    direktorat_options = _distinct_values(rows, 'direktorat')
    kode_pp_options = _distinct_values(rows, 'kodePP')
    direktorat = _multi_filter(request, 'direktorat', direktorat_options)
    kode_pp = _multi_filter(request, 'kode_pp', kode_pp_options)
    bulan_values = _multi_filter(request, 'bulan', MONTHS)
    search = (request.GET.get('q') or '').strip()

    month_range = None
    if filters['triwulan'] is not None:
        month_range = [(filters['triwulan'] - 1) * 3, filters['triwulan'] * 3 - 1]

    filtered = []
    for r in rows:
        if filters['triwulan'] is not None and r['tahun'] != filters['tahun']:
            continue
        if month_range is not None:
            if r['monthIdx'] < month_range[0] or r['monthIdx'] > month_range[1]:
                continue
        elif bulan_values and r['month'] not in bulan_values:
            continue
        if direktorat and r['direktorat'] not in direktorat:
            continue
        if kode_pp and r['kodePP'] not in kode_pp:
            continue
        if search:
            hay = f"{r['nama']} {r['kodePP']}".lower()
            if search.lower() not in hay:
                continue
        filtered.append(r)

    sort_col = request.GET.get('sort') if request.GET.get('sort') in SORTABLE else None
    dir_ = 'desc' if (request.GET.get('dir') or 'asc').lower() == 'desc' else 'asc'
    if sort_col is not None:
        # PHP's sortBy('bulan') sorts by the month *name* string; the rows key
        # is 'month' ('bulan' maps to it via the SORTABLE alias).
        key = 'month' if sort_col == 'bulan' else sort_col
        filtered.sort(key=lambda r: r[key], reverse=(dir_ == 'desc'))

    return {
        'filters': filters,
        'rows': filtered,
        'tahun': tahun_values,
        'bulan': bulan_values,
        'tahunOptions': tahun_options,
        'bulanOptions': MONTHS,
        'direktorat': direktorat,
        'kodePP': kode_pp,
        'direktoratOptions': direktorat_options,
        'kodePPOptions': kode_pp_options,
        'search': search,
        'sort': sort_col,
        'dir': dir_,
    }


def _query_link(query, extra=None):
    """Build a query string exactly like the original Laravel
    http_build_query: multi-valued keys as tahun[0]=2025&tahun[1]=2026,
    with None values dropped."""
    import urllib.parse
    parts = []
    for k, v in query.items():
        if v is None:
            continue
        if isinstance(v, list):
            for i, item in enumerate(v):
                parts.append(f'{k}[{i}]={urllib.parse.quote(str(item), safe="")}')
        else:
            parts.append(f'{k}={urllib.parse.quote(str(v), safe="")}')
    if extra:
        for k, v in extra.items():
            if v is None:
                continue
            parts.append(f'{k}={urllib.parse.quote(str(v), safe="")}')
    return '&'.join(parts)


def _page_list(page, pages):
    """Page numbers to render with '...' gaps, mirroring the Blade loop:
    first, last, and the window page-1..page+1; positions page-2/page+2
    become ellipsis markers (0)."""
    out = []
    for p in range(1, pages + 1):
        if p == 1 or p == pages or (page - 1 <= p <= page + 1):
            out.append(p)
        elif p == page - 2 or p == page + 2:
            out.append(0)
    return out


def realisasi(request):
    d = _realisasi_rows(request)
    filters = d['filters']
    filtered = d['rows']

    try:
        per_page = max(1, int(request.GET.get('per_page', '20')))
    except (TypeError, ValueError):
        per_page = 20
    total = len(filtered)
    try:
        page = max(1, int(request.GET.get('page', '1')))
    except (TypeError, ValueError):
        page = 1
    start = (page - 1) * per_page
    paged = filtered[start:start + per_page]

    sums = {
        'nilai': sum(r['nilai'] for r in filtered),
        'totalPendapatan': sum(r['totalPendapatan'] for r in filtered),
        'pendapatanBerjalan': sum(r['pendapatanBerjalan'] for r in filtered),
    }

    query = {
        'tipe': filters['tipe'],
        'q': d['search'],
        'per_page': per_page,
    }
    if filters['triwulan'] is not None:
        query['triwulan'] = filters['triwulan']
    if d['tahun'] != []:
        query['tahun'] = d['tahun']
    elif 'triwulan' not in query:
        query['tahun'] = [filters['tahun']]
    if d['bulan'] != []:
        query['bulan'] = d['bulan']
    if d['direktorat'] != []:
        query['direktorat'] = d['direktorat']
    if d['kodePP'] != []:
        query['kode_pp'] = d['kodePP']
    if d['sort'] is not None:
        query['sort'] = d['sort']
        query['dir'] = d['dir']

    def sort_url(col):
        dir_ = 'desc' if d['sort'] == col and d['dir'] == 'asc' else 'asc'
        q = dict(query)
        q['sort'] = col
        q['dir'] = dir_
        q['per_page'] = per_page
        q.pop('page', None)
        return '/data?' + _query_link(q)

    def page_url(p):
        q = dict(query)
        q['page'] = p
        return '/data?' + _query_link(q)

    pages = max(1, -(-total // per_page))

    return render(request, 'realisasi.html', {
        'rows': paged,
        'total': total,
        'page': page,
        'perPage': per_page,
        'pages': pages,
        'query': query,
        'grandTotal': sums,
        'tahun': d['tahun'],
        'bulan': d['bulan'],
        'tahunOptions': d['tahunOptions'],
        'bulanOptions': d['bulanOptions'],
        'triwulan': filters['triwulan'],
        'tipe': filters['tipe'],
        'direktorat': d['direktorat'],
        'kodePP': d['kodePP'],
        'direktoratOptions': d['direktoratOptions'],
        'kodePPOptions': d['kodePPOptions'],
        'sort': d['sort'],
        'dir': d['dir'],
        'sortUrl': sort_url,
        'pageUrl': page_url,
        'queryString': _query_link(query),
        'q': d['search'],
        'start_row': (page - 1) * per_page + 1,
        'first_display': min(start + 1, total) if total else 0,
        'last_display': min(start + per_page, total),
        'prev_page': max(1, page - 1),
        'next_page': min(pages, page + 1),
        'triwulan_labels': ['TW I', 'TW II', 'TW III', 'TW IV'],
        'arrow_map': {c: ('▲' if d['sort'] == c and d['dir'] == 'asc' else '▼' if d['sort'] == c else '') for c in SORTABLE},
        'page_list': _page_list(page, max(1, -(-total // per_page))),
        'fonts_head': _fonts_head(),
        'assets_head': _assets_head(),
        'active': 'realisasi',
    })


def export(request):
    d = _realisasi_rows(request)
    filtered = d['rows']
    filename = f"data-realisasi-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"

    response = HttpResponse(content_type='text/csv; charset=UTF-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(['No', 'Tahun', 'Bulan', 'Unit', 'No PP', 'Kode PP', 'Nama Proyek', 'Nilai Proyek (Rp)', 'Total Pendapatan Diakui (Rp)', 'Pendapatan Tahun Berjalan (Rp)'])
    for i, r in enumerate(filtered):
        writer.writerow([i + 1, r['tahun'], r['month'], r['unit'], r['noPP'], r['kodePP'], r['nama'], r['nilai'], r['totalPendapatan'], r['pendapatanBerjalan']])
    return response
