"""Revenue module views (pages + JSON).

Routes mounted under /dashboard/revenue/. Every page uses the SAME
RevenueContext so KPI / composition / series / performance agree.
"""
import json
from datetime import date
from decimal import Decimal

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from dashboard.views import _assets_head, _fonts_head

from .models import FinancialPeriod, Project, SimkugSyncLog
from .selectors import revenue_selectors as rsel
from .services import revenue_service as rs
from .services import revenue_project_service as rps
from .services.revenue_context import RevenueContext, month_name
from .services.formatters import format_rupiah_compact, format_percent


def _ctx_from_request(request):
    return RevenueContext(
        request,
        year=request.GET.get('year'),
        month=request.GET.get('month'),
        revenue_type=request.GET.get('type'),
        organization_id=request.GET.get('org'),
        pp_code=request.GET.get('pp'),
        account_code=request.GET.get('account'),
    )


def _base_ctx(request, ctx=None, active_tab='revenue_overview'):
    ctx = ctx or _ctx_from_request(request)
    years, months = rsel.period_options()
    opts = rsel.cascade_options(ctx.organization, ctx.revenue_type)
    last_sync = SimkugSyncLog.objects.filter(status__in=['SUCCESS', 'PARTIAL']).order_by('-finished_at').first()
    return {
        'ctx': ctx,
        'years': years,
        'months': months,
        'categories': opts['categories'],
        'organizations': opts['organizations'],
        'pps': opts['pps'],
        'accounts': opts['accounts'],
        'last_sync': last_sync,
        'assets_head': _assets_head(),
        'fonts_head': _fonts_head(),
        'active': 'dashboard',
        'active_tab': active_tab,
    }


# --------------------------------------------------------------------------
# Overview (2 KPI YTD + composition + charts + org/PP table)
# --------------------------------------------------------------------------
def overview(request):
    # Canonical Revenue Overview lives at /dashboard/ (mock page with the
    # dashboard visual language). Keep /dashboard/revenue/ as a redirect so
    # old bookmarks/sidebar links still land on the real page.
    from django.shortcuts import redirect
    return redirect('dashboard', permanent=True)





def filter_pps(request):
    """Cascade: PP options for an organization (JSON)."""
    from .models import PPMaster
    org_id = request.GET.get('org') or 'all'
    qs = PPMaster.objects.filter(is_active=True).select_related('organization_unit')
    if org_id not in ('all', '', 'Semua') and str(org_id).isdigit():
        qs = qs.filter(organization_unit_id=int(org_id))
    return JsonResponse(
        [{'value': p.pp_code, 'label': f'{p.pp_code} · {p.organization_unit.name if p.organization_unit else ""}'} for p in qs],
        safe=False,
    )


def filter_accounts(request):
    """Cascade: account options for a revenue type (JSON)."""
    from .models import RevenueAccount, RevenueCategory
    rtype = request.GET.get('type') or 'all'
    qs = RevenueAccount.objects.filter(is_active=True).select_related('revenue_category')
    if rtype not in ('all', '', 'Semua'):
        cat = RevenueCategory.objects.filter(code=rtype).first()
        if cat:
            qs = qs.filter(revenue_category=cat)
    return JsonResponse(
        [{'value': a.account_code, 'label': f'{a.account_code} · {a.account_name}'} for a in qs],
        safe=False,
    )


# --------------------------------------------------------------------------
# TF / NTF Research detail (org x PP x account grain; no project structure)
# --------------------------------------------------------------------------
_GL_SORTABLE = ['organization', 'pp_code', 'kode_akun', 'nama_akun',
                 'realisasi_bulan', 'realisasi_ytd', 'rka_ytd']
_GL_PER_PAGE = [20, 50, 100]


def _gl_list(request, revenue_type):
    """TF / NTF Research page.

    TF has no Project Master: one main row = ONE account in ONE month of the
    selected year (e.g. 'Pendapatan Pendaftaran Agustus 2026'); the expand
    panel lists the GL transactions behind that month (per PP / bank channel).
    Column values equal the month total (TF income is recognised in the period
    it is received), so Total Pendapatan == Pendapatan Berjalan == sum of the
    detail rows.
    """
    ctx = _ctx_from_request(request)
    if ctx.revenue_type in ('', 'all', 'Semua'):
        ctx = RevenueContext(year=ctx.year, month=ctx.month, revenue_type=revenue_type,
                             organization_id=ctx.organization.pk if ctx.organization else None,
                             pp_code=ctx.pp.pp_code if ctx.pp else None,
                             account_code=ctx.revenue_account.account_code if ctx.revenue_account else None)

    search = (request.GET.get('q') or '').strip()
    sort = request.GET.get('sort') if request.GET.get('sort') in _NTF_SORTABLE else ''
    direction = 'desc' if (request.GET.get('dir') or 'asc').lower() == 'desc' else 'asc'
    try:
        per_page = int(request.GET.get('per_page', '20'))
        if per_page not in _NTF_PER_PAGE:
            per_page = 20
    except (TypeError, ValueError):
        per_page = 20

    if revenue_type == 'TF':
        # Data TF = per program (Project TF-) x PP: one row per real TF
        # program (Pendaftaran PIN SMBB, QRMO, Pusat Bahasa, …). Nilai =
        # program's RKA allocation; figures from mapped GL (like NTF).
        all_rows = rps.tf_program_rows(ctx, search=search,
                                       sort=sort, direction=direction)
    else:
        # NTF Research = per objek hibah/penelitian (Project RS-) x PP.
        all_rows = rps.research_object_rows(ctx, search=search,
                                            sort=sort, direction=direction)

    # Normalise once for ALL rows (grand totals + page slice) so both the
    # row list and the grand-total line see the aliased fields.
    for r in all_rows:
        r['bulan'] = month_name(r['bulan'])
        # gl_grain_rows uses kode_akun/nama_akun/realisasi_*; alias to the
        # shared display fields (tf_account_pp_rows already uses akun/nama).
        if 'kode_akun' in r:
            r['akun'] = r.get('kode_akun') or ''
            r['akun_nama'] = r.get('nama_akun') or ''
            r['nama'] = r.get('nama_akun') or r.get('nama') or '-'
            r['total_pendapatan'] = r.get('realisasi_bulan', Decimal('0'))
            r['pendapatan_berjalan'] = r.get('realisasi_ytd', Decimal('0'))
            r['month'] = ctx.month
        r['nama'] = r['nama'] or '-'
        r['nama_proyek'] = (r.get('nama_proyek') or '').strip() or '-'
        # Pendapatan Pendaftaran (4111101, PERIOD_ONLY) is a period-specific
        # receipt batch: Nilai Proyek == Total Pendapatan == Pendapatan Diakui
        # == the selected month's realisasi, progress 100% (FULLY). The
        # Project Master value is a whole-program number and must NOT be
        # shown against one month's batch.
        if r.get('detail_mode') == 'PERIOD_ONLY':
            _m = r.get('realisasi_bulan') or Decimal('0')
            r['nilai'] = _m
            r['total_pendapatan'] = _m
            r['pendapatan_berjalan'] = _m
    total = len(all_rows)
    try:
        page = max(1, int(request.GET.get('page', '1')))
    except (TypeError, ValueError):
        page = 1
    pages = max(1, -(-total // per_page))
    page = min(page, pages)
    start = (page - 1) * per_page
    rows = all_rows[start:start + per_page]

    for r in rows:
        if r.get('mode') == 'tf_program':
            # akun already carries the full 'KODE Nama' label from the mapper.
            r['akun_disp'] = r['akun']
            r['kode_akun'] = (r['akun'] or '').split(' ')[0] if r['akun'] else ''
        else:
            r['akun_disp'] = (r['akun'] + ' ' + (r.get('akun_nama') or '')).strip() if r['akun'] != '' else ''
        # text cells: empty -> dash
        for _k in ('unit', 'no_proyek', 'pp_code', 'organization'):
            r[_k] = (r.get(_k) or '').strip() or '-'
        if r.get('mode') == 'tf_program':
            # One row = one project/objek per PP per account. Column semantics:
            #   Nilai Proyek       = project value (Project Master, never GL);
            #                        '—' when unmapped.
            #   Pendapatan Diakui  = revenue recognised in the SELECTED MONTH.
            #   Total Pendapatan   = lifetime recognized up to period end.
            #   progress           = Total / Nilai Proyek.
            if r.get('detail_mode') == 'PERIOD_ONLY':
                # Pendaftaran: batch of the month -> Total = the month itself
                total_val = r['total_pendapatan'] or r['realisasi_bulan']
                _nv = r['nilai'] or 0
                r['nilai_disp'] = _rupiah(_nv) if _nv > 0 else '—'
                r['total_disp'] = _rupiah(total_val)
                r['berjalan_disp'] = _rupiah(r['pendapatan_berjalan'])  # month
                _pct_prog = 100 if _nv > 0 else 0
            else:
                total_val = r['total_pendapatan']   # lifetime up to period
                _nv = r['nilai'] or 0
                r['nilai_disp'] = '—' if _nv <= 0 else _rupiah(_nv)
                r['total_disp'] = _rupiah(total_val)
                r['berjalan_disp'] = _rupiah(r['pendapatan_berjalan'])  # month
                # Progress = PROJECT total revenue (all accounts, up to
                # period) / project value; multi-account rows share ONE
                # project progress.
                _ptot = r.get('project_total_pendapatan') or r['total_pendapatan']
                if _nv > 0:
                    try:
                        _pct_prog = int(round(float(_ptot) / max(1.0, float(_nv)) * 100))
                    except (TypeError, ValueError):
                        _pct_prog = 0
                else:
                    _pct_prog = 0
        elif r.get('mode') == 'account_month':
            total = r['total_pendapatan']
            r['nilai_disp'] = _rupiah(total)
            r['total_disp'] = _rupiah(total)
            r['berjalan_disp'] = _rupiah(total)
            _pct_prog = 100
        else:
            r['nilai_disp'] = 'Rp0'
            r['total_disp'] = _rupiah(r['total_pendapatan'])
            r['berjalan_disp'] = _rupiah(r['pendapatan_berjalan'])
            try:
                _pct_prog = int(round(float(r['pendapatan_berjalan']) / max(1.0, float(r['total_pendapatan'])) * 100))
            except (TypeError, ValueError):
                _pct_prog = 0
        if not r.get('akun_disp'):
            r['akun_disp'] = '-'
        r['progress_width'] = min(100, _pct_prog)
        r['progress_color'] = _progress_color(_pct_prog)
        r['no'] = None  # filled by template via counter

    # Grand totals follow the row semantics:
    #   Nilai  = sum RKA YTD (TF) / Rp0 (research rows have no nilai)
    #   Total  = sum realisasi YTD
    #   Diakui = sum realisasi bulan terpilih
    # Grand total Nilai = SUM DISTINCT project value (a project split across
    # accounts must count once); Total/Diakui = sum per-row revenue.
    _seen_proj = set()
    g_nilai = Decimal('0')
    for r in all_rows:
        proj = r.get('project')
        pk = getattr(proj, 'pk', None)
        if pk is not None and pk in _seen_proj:
            continue
        if pk is not None:
            _seen_proj.add(pk)
        g_nilai += r.get('nilai') or Decimal('0')
    if revenue_type == 'TF':
        g_total = sum(
            (r.get('realisasi_bulan') or 0) if r.get('detail_mode') == 'PERIOD_ONLY'
            else (r.get('total_pendapatan') or 0)
            for r in all_rows)
    else:
        g_total = sum(r['total_pendapatan'] for r in all_rows)
    g_berjalan = sum(r['pendapatan_berjalan'] for r in all_rows)
    grand = {
        # Nilai Proyek grand: distinct per project; '—' when nothing mapped
        'nilai_disp': _rupiah(g_nilai) if g_nilai > 0 else '—',
        'total_disp': _rupiah(g_total),
        'berjalan_disp': _rupiah(g_berjalan),
    }

    page_name = 'TF' if revenue_type == 'TF' else 'NTF Research'
    tab = 'revenue_tf' if revenue_type == 'TF' else 'revenue_ntf_research'

    def query_base():
        q = {'year': ctx.year, 'month': ctx.month}
        if ctx.organization is not None:
            q['org'] = ctx.organization.pk
        if ctx.pp is not None:
            q['pp'] = ctx.pp.pp_code
        if ctx.revenue_account is not None:
            q['account'] = ctx.revenue_account.account_code
        if search:
            q['q'] = search
        if per_page != 20:
            q['per_page'] = per_page
        return q

    def sort_url(col):
        q = query_base()
        q['sort'] = col
        q['dir'] = 'desc' if (sort == col and direction == 'asc') else 'asc'
        return request.path + '?' + _qs(q)

    def page_url(pg):
        q = query_base()
        q['page'] = pg
        return request.path + '?' + _qs(q)

    return render(request, 'finance/revenue/account_list.html', {
        **_base_ctx(request, ctx, tab),
        'ctx': ctx,
        'rows': rows,
        'grand': grand,
        'total': total,
        'page': page,
        'pages': pages,
        'per_page': per_page,
        'per_page_options': _NTF_PER_PAGE,
        'q': search,
        'sort': sort,
        'dir': direction,
        'sortUrl': sort_url,
        'pageUrl': page_url,
        'first_display': min(start + 1, total) if total else 0,
        'last_display': min(start + per_page, total),
        'prev_page': max(1, page - 1),
        'next_page': min(pages, page + 1),
        'arrow_map': {c: ('▲' if sort == c and direction == 'asc' else '▼' if sort == c else '') for c in _NTF_SORTABLE},
        'page_name': page_name,
        'month_label': month_name(ctx.month),
        'page_list': _page_list(page, pages),
    })


def _rupiah(v):
    try:
        return 'Rp' + f'{int(v):,}'.replace(',', '.')
    except (TypeError, ValueError):
        return 'Rp0'


def tf_detail(request):
    return _gl_list(request, 'TF')


def ntf_research_detail(request):
    return _gl_list(request, 'NTF_RESEARCH')


# --------------------------------------------------------------------------
# NTF Project LIST mirrors the existing "Data Realisasi" grid table.
# One row = one project. Columns follow the realisasi visual contract.
# --------------------------------------------------------------------------
_NTF_SORTABLE = ['tahun', 'bulan', 'unit', 'no_proyek', 'kode_pp',
                 'organization', 'nama', 'nama_proyek', 'akun',
                 'nilai', 'total_pendapatan', 'pendapatan_berjalan']
_NTF_PER_PAGE = [20, 50, 100]


def ntf_project_list(request):
    ctx = _ctx_from_request(request)

    # search + sort + pagination (same query-string contract as realisasi)
    search = (request.GET.get('q') or '').strip()
    sort = request.GET.get('sort') if request.GET.get('sort') in _NTF_SORTABLE else ''
    direction = 'desc' if (request.GET.get('dir') or 'asc').lower() == 'desc' else 'asc'
    try:
        per_page = int(request.GET.get('per_page', '20'))
        if per_page not in _NTF_PER_PAGE:
            per_page = 20
    except (TypeError, ValueError):
        per_page = 20

    # NTF Project = contract projects (P-) + layanan/sertifikasi objek (SRV-)
    all_rows = rps.project_rows(ctx, search=search, sort=sort, direction=direction)
    all_rows += rps.service_object_rows(ctx, search=search, sort=sort, direction=direction)
    # contract projects reuse the same objek-row display shape
    for r in all_rows:
        if 'project_number' not in r:
            pass
        if r.get('mode') != 'tf_program':
            # contract project rows (project_rows): Nama Proyek = project name,
            # Nama Akun = mapped account name (split from 'KODE Nama' label).
            r['mode'] = 'tf_program'
            r['nama_proyek'] = r.get('nama') or r.get('project_name') or '-'
            _acc_parts = (r.get('akun') or '').split(' ', 1)
            r['akun'] = _acc_parts[0] if _acc_parts and _acc_parts[0].isdigit() else (r.get('akun') or '')
            r['akun_nama'] = _acc_parts[1] if len(_acc_parts) > 1 else (r.get('akun') or '')
            r['nama'] = r['akun_nama'] or '-'
            r['project'] = r.get('project')
        r['nama_proyek'] = (r.get('nama_proyek') or r.get('nama') or '-')
    total = len(all_rows)

    try:
        page = max(1, int(request.GET.get('page', '1')))
    except (TypeError, ValueError):
        page = 1
    pages = max(1, -(-total // per_page))
    page = min(page, pages)
    start = (page - 1) * per_page
    rows = all_rows[start:start + per_page]
    for r in rows:
        r['bulan'] = month_name(r['bulan'])
        # text cells: empty -> dash
        for k in ('nama', 'nama_proyek', 'unit', 'organization', 'no_proyek', 'pp_code', 'akun', 'akun_nama'):
            r[k] = (r.get(k) or '').strip() or '-'
        # display money (same semantics as Data TF, mode='tf_program'):
        #   Nilai Proyek = Project Master value; 0/unmapped -> '—' (never Rp0)
        #   Total        = account lifetime up to period
        #   Diakui       = account YTD (Jan..selected month)
        _nv = r['nilai'] or 0
        r['nilai_disp'] = '—' if _nv <= 0 else _rupiah(_nv)
        r['total_disp'] = _rupiah(r['total_pendapatan'])      # lifetime (row/account)
        r['berjalan_disp'] = _rupiah(r['pendapatan_berjalan'])  # month
        # Progress = project-level revenue (all accounts) / project value.
        _ptot = r.get('project_total_pendapatan') or r['total_pendapatan']
        if _nv > 0:
            try:
                _pct = int(round(float(_ptot) / max(1.0, float(_nv)) * 100))
            except (TypeError, ValueError):
                _pct = 0
        else:
            _pct = 0
        r['progress_width'] = min(100, _pct)
        r['progress_color'] = _progress_color(_pct)

    # Grand total: Nilai = SUM DISTINCT project value (project split across
    # accounts counts once); Total/Diakui = sum per-account revenue.
    _seen = set()
    g_nilai = Decimal('0')
    for r in all_rows:
        pk = r.get('project') and getattr(r['project'], 'pk', None)
        if pk is not None:
            if pk in _seen:
                continue
            _seen.add(pk)
        g_nilai += r.get('nilai') or Decimal('0')
    g_total = sum(r['total_pendapatan'] for r in all_rows)
    g_berjalan = sum(r['pendapatan_berjalan'] for r in all_rows)
    grand = {
        'nilai_disp': _rupiah(g_nilai) if g_nilai > 0 else '—',
        'total_disp': _rupiah(g_total),
        'berjalan_disp': _rupiah(g_berjalan),
    }

    def query_base():
        q = {'year': ctx.year, 'month': ctx.month}
        if ctx.organization is not None:
            q['org'] = ctx.organization.pk
        if ctx.pp is not None:
            q['pp'] = ctx.pp.pp_code
        if ctx.revenue_account is not None:
            q['account'] = ctx.revenue_account.account_code
        if search:
            q['q'] = search
        if per_page != 20:
            q['per_page'] = per_page
        return q

    def sort_url(col):
        q = query_base()
        q['sort'] = col
        q['dir'] = 'desc' if (sort == col and direction == 'asc') else 'asc'
        return '/dashboard/revenue/ntf-project/?' + _qs(q)

    def page_url(p):
        q = query_base()
        q['page'] = p
        return '/dashboard/revenue/ntf-project/?' + _qs(q)

    return render(request, 'finance/revenue/account_list.html', {
        **_base_ctx(request, ctx, 'revenue_ntf_project'),
        'page_name': 'NTF Project',
        'ctx': ctx,
        'rows': rows,
        'grand': grand,
        'total': total,
        'page': page,
        'pages': pages,
        'per_page': per_page,
        'per_page_options': _NTF_PER_PAGE,
        'q': search,
        'sort': sort,
        'dir': direction,
        'sortUrl': sort_url,
        'pageUrl': page_url,
        'first_display': min(start + 1, total) if total else 0,
        'last_display': min(start + per_page, total),
        'prev_page': max(1, page - 1),
        'next_page': min(pages, page + 1),
        'arrow_map': {c: ('▲' if sort == c and direction == 'asc' else '▼' if sort == c else '') for c in _NTF_SORTABLE},
        'month_label': month_name(ctx.month),
        'page_list': _page_list(page, pages),
    })


def _qs(query):
    import urllib.parse
    parts = []
    for k, v in query.items():
        if v is None:
            continue
        parts.append(f'{k}={urllib.parse.quote(str(v), safe="")}')
    return '&'.join(parts)


def _progress_color(pct):
    if pct < 50:
        return '#FF383C'
    if pct < 70:
        return '#FACC15'
    if pct < 80:
        return '#FF8D28'
    return '#10B981'


# --------------------------------------------------------------------------
# Recognition history (expandable row fragment)
# --------------------------------------------------------------------------
def project_recognitions(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    ctx = _ctx_from_request(request)
    acc_filter = request.GET.get('account') or None
    is_period_only = False
    if project.project_number.startswith('TF-'):
        # Data TF program: scope follows the mapped account's mode.
        #   PERIOD_ONLY (Pend. Pendaftaran) -> exact selected month/year.
        #   HISTORICAL (education programs) -> recognition history of the same
        #       program up to the selected period (earlier months/years stay).
        mode = rps.project_account_mode(project)
        is_period_only = mode == 'PERIOD_ONLY'
        if is_period_only:
            history = rps.recognition_history(project, year=ctx.year, month=ctx.month, account_code=acc_filter)
        else:
            # HISTORICAL: recognition history of the same object up to the
            # selected period end (earlier months/years included; nothing
            # after the selected period).
            import calendar
            _last = calendar.monthrange(ctx.year, ctx.month)[1]
            _end = date(ctx.year, ctx.month, _last)
            history = rps.recognition_history(project, upto_date=_end, account_code=acc_filter)
    else:
        # NTF Project: full termin recognition history (any period) so
        # Termin I/II/III across months/years stay visible for the project.
        history = rps.recognition_history(project, account_code=acc_filter)
    summary = rps.project_summary(project, ctx.year, ctx.month)
    # When a row is one account of the project, expand summary figures must
    # follow that account (never the whole project's aggregate).
    if acc_filter:
        acc_tot = rps.project_account_totals(project, ctx.year, ctx.month).get(acc_filter, {})
        acc_name = next((a['name'] for a in rps.project_accounts(project) if a['code'] == acc_filter), '')
        acc_lifetime = acc_tot.get('lifetime', Decimal('0'))
        acc_ytd = acc_tot.get('ytd', Decimal('0'))
        summary = dict(summary)
        summary['lifetime'] = acc_lifetime
        summary['ytd'] = acc_ytd
        summary['recognized_month'] = acc_tot.get('month', Decimal('0'))
        summary['acc_name'] = acc_name
        # Recognition = Total Pendapatan / Nilai Proyek (per spec 7)
        summary['recognition_pct'] = (acc_lifetime / project.project_value * Decimal('100')) if project.project_value else None
    history_disp = [{
        'date': h['date'],
        'voucher': h['voucher'],
        'document': h['document'],
        'description': h['description'],
        'account_code': h['account_code'],
        'account_name': h['account_name'],
        'amount': 'Rp' + f'{int(h["amount"]):,}'.replace(',', '.'),
    } for h in history]
    month_full = month_name(ctx.month)
    month_short = month_name(ctx.month)[:3] if ctx.month else ''
    detail_mode = 'PERIOD_ONLY' if is_period_only else 'HISTORICAL'
    is_tf_program = project.project_number.startswith('TF-')
    acc_name = summary.get('acc_name', '')
    ctx_disp = {
        'month': format_rupiah_compact(summary['recognized_month']),
        'ytd': format_rupiah_compact(summary['ytd']),
        'lifetime': format_rupiah_compact(summary['lifetime']),
        'remaining': format_rupiah_compact(summary['remaining']),
        'pct': format_percent(summary['recognition_pct']),
        'detail_mode': detail_mode,
        'is_tf_program': is_tf_program,
        'acc_name': acc_name,
        'acc_code': acc_filter or '',
        # Nilai Proyek: formatted project value; '—' when unmapped (0)
        'nilai': ('Rp' + f'{int(project.project_value):,}'.replace(',', '.'))
                 if project.project_value > 0 else '—',
        'nilai_ok': project.project_value > 0,
    }
    frag_ctx = {
        'project': project, 'history': history_disp, 'history_disp': history_disp,
        'summary': summary, 'summary_disp': ctx_disp, 'ctx': ctx,
        'month_full': month_full, 'month_short': month_short, 'dash': '-',
    }
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        from django.template.loader import render_to_string
        return JsonResponse({'html': render_to_string('finance/revenue/_recognitions_fragment.html', frag_ctx)})
    return render(request, 'finance/revenue/project_recognitions.html', {
        **_base_ctx(request, ctx, 'revenue_ntf_project'),
        **frag_ctx,
    })


# --------------------------------------------------------------------------
# Data quality / admin control
# --------------------------------------------------------------------------
def data_quality(request):
    from django.db.models import Count as _Count, Sum as _Sum
    from .models import RevenueLedger, SimkugSyncLog, RkaVersion
    from .services.revenue_budget_service import validate_phasing
    from .services.revenue_matching_service import review_stats

    period_id = request.GET.get('period')
    period = None
    if period_id and period_id.isdigit():
        period = FinancialPeriod.objects.filter(pk=int(period_id)).first()
    stats = review_stats(period)
    syncs = SimkugSyncLog.objects.all()[:10]
    active_versions = RkaVersion.objects.filter(is_active=True)
    phasing_mismatch = []
    for v in active_versions:
        phasing_mismatch += validate_phasing(v)
    unmapped_accounts = (
        RevenueLedger.objects.filter(revenue_account__isnull=True)
        .values('account_code_raw', 'account_name_raw')
        .annotate(n=_Count('id'), total=_Sum('credit'))
        .order_by('-total')[:20]
    )
    periods = FinancialPeriod.objects.order_by('-year', '-month')
    return render(request, 'finance/revenue/data_quality.html', {
        **_base_ctx(request), 'stats': stats, 'syncs': syncs,
        'phasing_mismatch': phasing_mismatch, 'unmapped_accounts': unmapped_accounts,
        'periods': periods, 'sel_period': period,
    })


def _page_list(page, pages):
    """Page numbers with '...' gaps, mirroring the Blade loop."""
    out = []
    for p in range(1, pages + 1):
        if p == 1 or p == pages or (page - 1 <= p <= page + 1):
            out.append(p)
        elif p == page - 2 or p == page + 2:
            out.append(0)
    return out


def account_recognitions(request):
    """AJAX fragment: GL rows behind one TF / NTF Research table row.

    Two modes:
    - month (TF): all GL of one account in one month expand panel lists
      the per-PP / bank-channel transactions behind 'Pendapatan X Bulan Y'.
    - pp+account (NTF Research): legacy GL history for one PP x Account.
    """
    ctx = _ctx_from_request(request)
    pp_code = request.GET.get('pp') or ''
    account_code = request.GET.get('account') or ''
    month_raw = request.GET.get('month') or ''
    activity = request.GET.get('activity') or ''
    from django.template.loader import render_to_string
    try:
        month = int(month_raw) if month_raw else ctx.month
    except (TypeError, ValueError):
        month = ctx.month
    if pp_code and account_code and month_raw:
        # Data TF row (PP x Account x Month): ONLY this PP's transactions.
        history = rps.tf_account_pp_gl(ctx, pp_code, account_code, month)
    elif month_raw:
        # account-month expansion (legacy) — all PPs of that account+month.
        history = rps.account_month_gl(ctx, account_code, month, activity=activity or None)
    else:
        # NTF Research: lifetime GL history for one PP x Account.
        history = rps.account_gl_history(ctx, pp_code, account_code)
    rows = [{
        'date': h['date'], 'voucher': h['voucher'], 'document': h['document'],
        'description': h['description'], 'account_code': h['account_code'],
        'account_name': h['account_name'],
        'pp_code': h.get('pp_code'), 'organization': h.get('organization'),
        'amount': 'Rp' + f'{int(h["amount"]):,}'.replace(',', '.'),
    } for h in history]
    return JsonResponse({'html': render_to_string('finance/revenue/_account_gl_fragment.html', {'rows': rows})})


