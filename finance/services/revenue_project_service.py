"""Project-level revenue (NTF Project list + recognition history).

Per-project figures are derived from mapped GL only (finance_glprojectmapping
-> finance_revenueledger); the NTF report's own recognized numbers are NEVER
authoritative. One main-table row = ONE project; termin rows only appear in
the expanded detail panel.
"""
import re

from decimal import Decimal

from django.db.models import Sum

from finance.models import (
    FinancialPeriod,
    GLProjectMapping,
    NtfReportSnapshot,
    Project,
    ProjectAlias,
)

ZERO = Decimal('0')

_MATCH_OK = ['AUTO_MATCHED', 'VERIFIED', 'NEEDS_REVIEW']


def _net(row):
    # mirrors revenue_service sign convention (credit - debit)
    return row.credit - row.debit


def _mapped(project, **ledger_filters):
    qs = GLProjectMapping.objects.filter(
        project=project, match_status__in=_MATCH_OK,
    )
    if ledger_filters:
        qs = qs.filter(**ledger_filters)
    return qs


def _sum_mapped(qs):
    total = ZERO
    for m in qs.select_related('ledger').iterator(chunk_size=1000):
        total += _net(m.ledger)
    return total


def project_lifetime(project):
    """Lifetime recognized = ALL mapped GL revenue (any period)."""
    return _sum_mapped(_mapped(project))


def project_month(project, period):
    if period is None:
        return ZERO
    return _sum_mapped(_mapped(project, ledger__period=period))


def project_ytd(project, year, month):
    """YTD = mapped GL Jan..selected month of the selected year."""
    return _sum_mapped(_mapped(
        project, ledger__period__year=year, ledger__period__month__lte=month
    ))


def project_accounts(project):
    """Distinct revenue accounts of a project's mapped GL (authoritative)."""
    rows = (GLProjectMapping.objects
            .filter(project=project, match_status__in=_MATCH_OK,
                    ledger__revenue_account__isnull=False)
            .values('ledger__revenue_account__account_code',
                    'ledger__revenue_account__account_name',
                    'ledger__revenue_account__detail_history_mode')
            .distinct()
            .order_by('ledger__revenue_account__account_code'))
    return [{'code': r['ledger__revenue_account__account_code'],
             'name': r['ledger__revenue_account__account_name'],
             'mode': r['ledger__revenue_account__detail_history_mode'] or 'HISTORICAL'}
            for r in rows]


def project_account_totals(project, year, month):
    """Per-account revenue of one project up to the selected period.

    Returns {account_code: {'lifetime': X, 'ytd': Y, 'month': Z}} where
    lifetime = mapped GL sum up to period end (all years),
    ytd      = mapped GL of the selected year up to month,
    month    = mapped GL of the selected year+month only.
    """
    from datetime import date as _date
    import calendar as _cal
    maps = (GLProjectMapping.objects
            .filter(project=project, match_status__in=_MATCH_OK,
                    ledger__revenue_account__isnull=False)
            .select_related('ledger', 'ledger__period', 'ledger__revenue_account'))
    end = _date(year, month, _cal.monthrange(year, month)[1])
    out = {}
    for m in maps:
        led = m.ledger
        acc = led.revenue_account
        code = acc.account_code if acc else (led.account_code_raw or '?')
        amt = led.credit - led.debit
        d = out.setdefault(code, {'lifetime': ZERO, 'ytd': ZERO, 'month': ZERO})
        if led.posting_date and led.posting_date <= end:
            d['lifetime'] += amt
            if led.period and led.period.year == year:
                d['ytd'] += amt
                if led.period.month == month:
                    d['month'] += amt
    return out


def project_status(lifetime, value):
    if lifetime == ZERO:
        return 'NO_REVENUE'
    if lifetime < value:
        return 'ON_PROGRESS'
    if lifetime == value:
        return 'FULLY_RECOGNIZED'
    return 'NEEDS_REVIEW'


def project_account_label(project):
    """Account display for a project (never arbitrary single pick):
    - exactly 1 mapped account  -> 'KODE Nama Akun'
    - >1 mapped accounts        -> 'Multi Akun · N'
    - no mapped GL              -> ''
    """
    rows = (
        GLProjectMapping.objects
        .filter(project=project, match_status__in=_MATCH_OK,
                ledger__revenue_account__isnull=False)
        .values('ledger__revenue_account__account_code',
                'ledger__revenue_account__account_name')
        .distinct()
    )
    accounts = [(r['ledger__revenue_account__account_code'], r['ledger__revenue_account__account_name']) for r in rows]
    if not accounts:
        return ''
    if len(accounts) == 1:
        code, name = accounts[0]
        return f'{code} {name}'.strip()
    return f'Multi Akun · {len(accounts)}'
''


def _project_unit(project):
    """Unit metadata from the latest NTF report snapshot (raw, non-authoritative
    financials used only for the Unit display column)."""
    snap = NtfReportSnapshot.objects.filter(project=project).order_by('-period__year', '-period__month', '-loaded_at').first()
    return snap.unit_raw if snap and snap.unit_raw else ''


def project_account_mode(project):
    """Expand-detail scope of a project/object: PERIOD_ONLY for periodic
    accounts (Pend. Pendaftaran) vs HISTORICAL for project-oriented income.
    Derives the mode from the project's mapped revenue account(s); defaults
    to HISTORICAL (project termin history) when nothing is mapped."""
    acc = (GLProjectMapping.objects
           .filter(project=project, match_status__in=_MATCH_OK,
                   ledger__revenue_account__isnull=False)
           .values_list('ledger__revenue_account__detail_history_mode', flat=True)
           .first())
    return acc or 'HISTORICAL'


def project_summary(project, year, month):
    """Single-project figures (main row / recognitions header)."""
    period = FinancialPeriod.objects.filter(year=year, month=month).first()
    lifetime = project_lifetime(project)
    value = project.project_value
    return {
        'project': project,
        'unit': _project_unit(project),
        'pp_code': project.pp.pp_code if project.pp else '',
        'organization': (
            project.organization_unit.name if project.organization_unit
            else (project.pp.organization_unit.name if project.pp and project.pp.organization_unit else '')
        ),
        'account_code': '',
        'account_name': '',
        'recognized_month': project_month(project, period),
        'ytd': project_ytd(project, year, month),
        'lifetime': lifetime,
        'remaining': value - lifetime,
        'recognition_pct': (lifetime / value * Decimal(100)) if value else None,
        'status': project_status(lifetime, value),
    }


def project_rows(ctx, *, search='', sort='', direction='asc'):
    """NTF PROJECT list rows one row per project.

    Visual contract follows Data Realisasi; columns per the sprint spec:
      expand, tahun, bulan, unit, no proyek, kode pp, organization,
      nama proyek, akun pendapatan (aggregate label), nilai proyek,
      total pendapatan (lifetime), pendapatan berjalan (YTD).
    NO 'tipe' column (page is fixed NTF Project). NO analytical columns.
    """
    qs = Project.objects.filter(is_active=True).exclude(
        project_number__startswith='TF-').select_related(
        'pp__organization_unit', 'organization_unit'
    )
    if ctx.organization is not None:
        qs = qs.filter(pp__organization_unit=ctx.organization)
    if ctx.pp is not None:
        qs = qs.filter(pp=ctx.pp)
    if ctx.revenue_account is not None:
        qs = qs.filter(
            gl_mappings__ledger__revenue_account=ctx.revenue_account
        ).distinct()

    q = (search or '').strip().lower()
    rows = []
    for project in qs.distinct().order_by('pp__pp_code', 'project_number'):
        pp_label = project.pp.pp_code if project.pp else ''
        org_name = (project.organization_unit.name if project.organization_unit
                    else (project.pp.organization_unit.name if project.pp and project.pp.organization_unit else ''))
        unit = _project_unit(project) or org_name
        accounts = project_accounts(project)
        if not accounts:
            if (project.project_value or 0) <= 0:
                continue
            accounts = [{'code': '', 'name': project.project_name, 'mode': 'HISTORICAL'}]
        per_acc = project_account_totals(project, ctx.year, ctx.month)
        # Project-level revenue up to the selected period (ALL accounts of the
        # project): drives the progress bar so multi-account rows share ONE
        # project progress (spec: progress = project total revenue / value).
        proj_total = sum((t.get('lifetime') or ZERO) for t in per_acc.values())
        for acc in accounts:
            code, name, mode = acc['code'], acc['name'], acc['mode']
            if q and q not in (project.project_number or '').lower() \
                    and q not in (project.project_name or '').lower() \
                    and q not in (pp_label or '').lower() \
                    and q not in (org_name or '').lower() \
                    and q not in (code or '').lower():
                continue
            totals = per_acc.get(code, {'lifetime': ZERO, 'ytd': ZERO, 'month': ZERO})
            rows.append({
                'project': project,
                'mode': 'tf_program',
                'tahun': ctx.year,
                'bulan': ctx.month,
                'month': ctx.month,
                'unit': unit or '-',
                'no_proyek': project.project_number or '',
                'pp_code': pp_label,
                'organization': org_name,
                'nama': name or '-',
                'nama_proyek': project.project_name or '',
                'akun': code,
                'akun_nama': name or '',
                'nilai': project.project_value,
                'total_pendapatan': totals['lifetime'],
                'pendapatan_berjalan': totals['month'],
                'realisasi_bulan': totals['month'],
                'realisasi_ytd': totals['ytd'],
                'detail_mode': mode,
                'status': project_status(totals['lifetime'], project.project_value),
                'project_total_pendapatan': proj_total,
                'detail_params': {'pp': pp_label, 'account': code, 'project_id': project.pk},
            })

    col_map = {
        'tahun': lambda r: r['tahun'],
        'bulan': lambda r: r['bulan'],
        'unit': lambda r: r['unit'].lower(),
        'no_proyek': lambda r: r['no_proyek'],
        'kode_pp': lambda r: r['pp_code'],
        'organization': lambda r: r['organization'].lower(),
        'nama': lambda r: r['nama'].lower(),
        'akun': lambda r: r['akun'].lower(),
        'nilai': lambda r: r['nilai'],
        'total_pendapatan': lambda r: r['total_pendapatan'],
        'pendapatan_berjalan': lambda r: r['pendapatan_berjalan'],
    }
    key = col_map.get(sort)
    if key is not None:
        rows.sort(key=key, reverse=(direction == 'desc'))
    else:
        rows.sort(key=lambda r: r['total_pendapatan'], reverse=True)
    return rows


def recognition_history(project, year=None, month=None, month_lte=None, upto_date=None, account_code=None):
    """Mapped GL rows = revenue recognition history (never cash assumption).

    Scope filters (combined):
      year         -> only that calendar year
      month        -> only that exact month
      month_lte    -> months <= value (within the given year)
      upto_date    -> posting_date <= date (historical up to the selected
                      period end; earlier years of the same object stay)
      account_code -> only GL of that revenue account (per-account rows)
    """
    qs = _mapped(project).select_related(
        'ledger', 'ledger__period', 'ledger__revenue_account'
    ).order_by('-ledger__posting_date', '-ledger__id')
    if account_code:
        qs = qs.filter(ledger__revenue_account__account_code=account_code)
    if upto_date is not None:
        qs = qs.filter(ledger__posting_date__lte=upto_date)
    elif year:
        qs = qs.filter(ledger__period__year=year)
        if month:
            qs = qs.filter(ledger__period__month=month)
        elif month_lte:
            qs = qs.filter(ledger__period__month__lte=month_lte)
    return [{
        'date': m.ledger.posting_date,
        'year': m.ledger.period.year,
        'month': m.ledger.period.month,
        'voucher': m.ledger.voucher_number,
        'document': m.ledger.document_number,
        'description': m.ledger.description_raw,
        'account_code': m.ledger.revenue_account.account_code if m.ledger.revenue_account else (m.ledger.account_code_raw or ''),
        'account_name': m.ledger.revenue_account.account_name if m.ledger.revenue_account else (m.ledger.account_name_raw or ''),
        'amount': _net(m.ledger),
    } for m in qs]


def gl_grain_rows(ctx, *, search='', sort='', direction='asc'):
    """TF / NTF Research rows at grain (period) x PP x Revenue Account.

    Visual follows Data Realisasi, but these categories have no Project
    Master / project_value, so the columns are: No, Tahun, Bulan,
    Organization, Kode PP, Tipe, Kode Akun, Nama Akun, Realisasi Bulan,
    Realisasi YTD (+ optional RKA YTD). No project columns, no progress,
    no termin rows.
    """
    from django.db.models import Sum as _Sum
    from finance.models import RevenueLedger as _RL

    category = ctx.category  # TF or NTF_RESEARCH (page-locked)
    if category is None:
        return []

    # --- month actual per (pp, account) ---
    base = _RL.objects.filter(
        period__year=ctx.year, period__month=ctx.month,
        revenue_account__isnull=False,
        revenue_account__revenue_category=category,
    )
    if ctx.organization is not None:
        base = base.filter(pp__organization_unit=ctx.organization)
    if ctx.pp is not None:
        base = base.filter(pp=ctx.pp)
    if ctx.revenue_account is not None:
        base = base.filter(revenue_account=ctx.revenue_account)

    month_rows = base.values(
        'pp_id', 'pp__pp_code', 'pp__organization_unit__name',
        'revenue_account__account_code', 'revenue_account__account_name',
    ).annotate(credit=_Sum('credit'), debit=_Sum('debit'))

    # --- YTD actual per (pp, account) ---
    ytd_base = _RL.objects.filter(
        period__year=ctx.year, period__month__lte=ctx.month,
        revenue_account__isnull=False,
        revenue_account__revenue_category=category,
    )
    if ctx.organization is not None:
        ytd_base = ytd_base.filter(pp__organization_unit=ctx.organization)
    if ctx.pp is not None:
        ytd_base = ytd_base.filter(pp=ctx.pp)
    if ctx.revenue_account is not None:
        ytd_base = ytd_base.filter(revenue_account=ctx.revenue_account)
    ytd_rows = ytd_base.values(
        'pp_id', 'revenue_account__account_code',
    ).annotate(credit=_Sum('credit'), debit=_Sum('debit'))
    ytd_map = {}
    for r in ytd_rows:
        ytd_map[(r['pp_id'], r['revenue_account__account_code'])] = (
            (r['credit'] or ZERO) - (r['debit'] or ZERO)
        )

    # --- RKA YTD per (pp, account) ---
    from finance.models import RevenueBudget as _RB
    rka_base = _RB.objects.filter(
        year=ctx.year, rka_version__is_active=True,
        revenue_account__revenue_category=category,
    )
    if ctx.organization is not None:
        rka_base = rka_base.filter(pp__organization_unit=ctx.organization)
    if ctx.pp is not None:
        rka_base = rka_base.filter(pp=ctx.pp)
    if ctx.revenue_account is not None:
        rka_base = rka_base.filter(revenue_account=ctx.revenue_account)
    rka_map = {}
    for b in rka_base.select_related('pp').prefetch_related('monthly_rows'):
        phased = [m.budget_amount for m in b.monthly_rows.filter(month__lte=ctx.month)]
        amount = sum(phased, ZERO) if phased else b.annual_budget * Decimal(ctx.month) / Decimal(12)
        rka_map[(b.pp_id, b.revenue_account.account_code)] = amount

    rows = []
    for r in month_rows:
        pp_key = r['pp_id']
        acc_code = r['revenue_account__account_code'] or ''
        net_month = (r['credit'] or ZERO) - (r['debit'] or ZERO)
        rows.append({
            'tahun': ctx.year,
            'bulan': ctx.month,
            'organization': r['pp__organization_unit__name'] or '',
            'pp_code': r['pp__pp_code'] or '',
            'tipe': category.code,
            'kode_akun': acc_code or '',
            'nama_akun': r['revenue_account__account_name'] or '',
            'realisasi_bulan': net_month,
            'realisasi_ytd': ytd_map.get((pp_key, acc_code), ZERO),
            'rka_ytd': rka_map.get((pp_key, acc_code), ZERO),
        })

    # search
    q = (search or '').strip().lower()
    if q:
        rows = [
            r for r in rows
            if q in r['organization'].lower() or q in r['pp_code'].lower()
            or q in r['kode_akun'].lower() or q in r['nama_akun'].lower()
        ]

    col_map = {
        'tahun': lambda r: r['tahun'],
        'bulan': lambda r: r['bulan'],
        'organization': lambda r: r['organization'].lower(),
        'pp_code': lambda r: r['pp_code'],
        'tipe': lambda r: r['tipe'],
        'kode_akun': lambda r: r['kode_akun'],
        'nama_akun': lambda r: r['nama_akun'].lower(),
        'realisasi_bulan': lambda r: r['realisasi_bulan'],
        'realisasi_ytd': lambda r: r['realisasi_ytd'],
        'rka_ytd': lambda r: r['rka_ytd'],
    }
    key = col_map.get(sort)
    if key is not None:
        rows.sort(key=key, reverse=(direction == 'desc'))
    else:
        rows.sort(key=lambda r: r['realisasi_ytd'], reverse=True)
    return rows


def tf_account_pp_rows(ctx, *, search='', sort='', direction='asc'):
    """Data TF main rows at the authoritative grain: (period x PP x account).

    Every row is ONE PP's revenue on ONE account for the selected period.
    Different PPs are NEVER merged; 'Semua PP' is only a filter, never a row
    value. Organization always comes from the PP master.

    Columns mirror the NTF table for visual consistency, but the figures are
    real GL / RKA data:
      unit            -> organization name (from PP master)
      no_proyek       -> account code (TF has no project number)
      pp_code         -> real PP
      organization    -> real org name of that PP
      nama            -> account name (e.g. 'Pendapatan Pendidikan')
      akun            -> account code
      nilai (RKA)     -> RKA YTD of (PP x account) = the recognised target;
                         for Pendapatan Pendaftaran (4111101) the source has
                         no project value, so nilai == realisasi YTD.
      total_pendapatan-> GL realisasi of the selected MONTH (PP x account)
      pendapatan_berjalan -> GL realisasi YTD (Jan..selected month)
      progress        -> berjalan / nilai (YTD vs RKA YTD)
    """
    from django.db.models import Sum as _Sum
    from finance.models import RevenueLedger as _RL, RevenueBudget as _RB

    category_code = ctx.category.code if ctx.category else None
    if category_code != 'TF':
        return []

    base = _RL.objects.filter(
        period__year=ctx.year, period__month=ctx.month,
        revenue_account__isnull=False,
        revenue_account__revenue_category__code='TF',
    )
    if ctx.organization is not None:
        base = base.filter(pp__organization_unit=ctx.organization)
    if ctx.pp is not None:
        base = base.filter(pp=ctx.pp)
    if ctx.revenue_account is not None:
        base = base.filter(revenue_account=ctx.revenue_account)

    month_rows = base.values(
        'pp_id', 'pp__pp_code', 'pp__organization_unit__name',
        'revenue_account__account_code', 'revenue_account__account_name',
    ).annotate(credit=_Sum('credit'), debit=_Sum('debit'))

    # YTD realisasi per (pp, account)
    ytd_qs = _RL.objects.filter(
        period__year=ctx.year, period__month__lte=ctx.month,
        revenue_account__isnull=False,
        revenue_account__revenue_category__code='TF',
    )
    if ctx.organization is not None:
        ytd_qs = ytd_qs.filter(pp__organization_unit=ctx.organization)
    if ctx.pp is not None:
        ytd_qs = ytd_qs.filter(pp=ctx.pp)
    if ctx.revenue_account is not None:
        ytd_qs = ytd_qs.filter(revenue_account=ctx.revenue_account)
    ytd_map = {}
    for r in ytd_qs.values('pp_id', 'revenue_account__account_code').annotate(
            credit=_Sum('credit'), debit=_Sum('debit')):
        ytd_map[(r['pp_id'], r['revenue_account__account_code'])] =             (r['credit'] or ZERO) - (r['debit'] or ZERO)

    # RKA YTD per (pp, account)
    rka_qs = _RB.objects.filter(
        year=ctx.year, rka_version__is_active=True,
        revenue_account__revenue_category__code='TF',
    )
    if ctx.organization is not None:
        rka_qs = rka_qs.filter(pp__organization_unit=ctx.organization)
    if ctx.pp is not None:
        rka_qs = rka_qs.filter(pp=ctx.pp)
    if ctx.revenue_account is not None:
        rka_qs = rka_qs.filter(revenue_account=ctx.revenue_account)
    rka_map = {}
    for b in rka_qs.select_related('pp', 'revenue_account').prefetch_related('monthly_rows'):
        phased = [m.budget_amount for m in b.monthly_rows.filter(month__lte=ctx.month)]
        amt = sum(phased, ZERO) if phased else b.annual_budget * Decimal(ctx.month) / Decimal(12)
        rka_map[(b.pp_id, b.revenue_account.account_code)] = amt

    # GL descriptions of the month per (pp, account): used for the
    # 'Nama Proyek' column (TF has no project master; the descriptions are
    # the only source of a business label for the receipt batch).
    desc_rows = base.order_by('pp_id', 'revenue_account__account_code', 'posting_date', 'id') \
        .values('pp_id', 'revenue_account__account_code', 'description_raw')
    desc_map = {}
    for d in desc_rows:
        key = (d['pp_id'], d['revenue_account__account_code'])
        raw = (d['description_raw'] or '').strip()
        if raw:
            desc_map.setdefault(key, []).append(raw)

    def _clean_desc(text):
        # 'Penerimaan Pendaftaran BNI PIN SMBB - 2026-08' -> 'Penerimaan Pendaftaran BNI PIN SMBB'
        # 'Penerimaan Pendapatan Pendidikan - 2026-08' -> 'Penerimaan Pendapatan Pendidikan'
        return re.sub(r'\s*-\s*\d{4}-\d{1,2}$', '', text).strip()

    rows = []
    for r in month_rows:
        pp_id = r['pp_id']
        acc_code = r['revenue_account__account_code'] or ''
        acc_name = r['revenue_account__account_name'] or ''
        org_name = r['pp__organization_unit__name'] or ''
        pp_code = r['pp__pp_code'] or ''
        month_net = (r['credit'] or ZERO) - (r['debit'] or ZERO)
        ytd_net = ytd_map.get((pp_id, acc_code), ZERO)
        rka_ytd = rka_map.get((pp_id, acc_code), ZERO)
        # Pendaftaran: no project value -> nilai == recognised total (YTD)
        nilai = ytd_net if acc_code == '4111101' else rka_ytd
        # Nama Proyek = distinct GL descriptions of this PP+account+month,
        # joined as a label (e.g. Pendaftaran -> bank channels).
        descs = []
        seen = set()
        for raw in desc_map.get((pp_id, acc_code), []):
            c = _clean_desc(raw)
            if c and c not in seen:
                seen.add(c)
                descs.append(c)
        rows.append({
            'mode': 'tf_account_pp',
            'tahun': ctx.year,
            'bulan': ctx.month,
            'month': ctx.month,
            'unit': org_name,
            'no_proyek': '',                # TF has no project number
            'nama_proyek': '; '.join(descs) if descs else acc_name,
            'pp_code': pp_code,
            'organization': org_name,
            'nama': acc_name,
            'akun': acc_code,
            'akun_nama': acc_name,
            'nilai': nilai,
            'total_pendapatan': month_net,   # realisasi bulan berjalan
            'pendapatan_berjalan': ytd_net,  # realisasi YTD
            'detail_params': {'pp': pp_code, 'account': acc_code, 'month': ctx.month},
        })
    # Pendapatan Pendaftaran row is named with the filtered month (e.g.
    # 'Pendapatan Pendaftaran Agustus 2026') since it is one receipt batch
    # per period; other TF accounts keep the plain account name.
    _full_months = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
                    'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember']
    for r in rows:
        if r['akun'] == '4111101':
            r['nama'] = f"{r['nama']} {_full_months[ctx.month - 1]} {ctx.year}"

    q = (search or '').strip().lower()
    if q:
        rows = [r for r in rows
                if q in r['organization'].lower() or q in r['pp_code'].lower()
                or q in r['akun'].lower() or q in r['nama'].lower()]

    col_map = {
        'tahun': lambda r: r['tahun'],
        'bulan': lambda r: r['bulan'],
        'unit': lambda r: r['unit'].lower(),
        'no_proyek': lambda r: r['no_proyek'],
        'kode_pp': lambda r: r['pp_code'],
        'organization': lambda r: r['organization'].lower(),
        'nama': lambda r: r['nama'].lower(),
        'nama_proyek': lambda r: r['nama_proyek'].lower(),
        'akun': lambda r: r['akun'],
        'nilai': lambda r: r['nilai'] or ZERO,
        'total_pendapatan': lambda r: r['total_pendapatan'],
        'pendapatan_berjalan': lambda r: r['pendapatan_berjalan'],
    }
    key = col_map.get(sort)
    if key is not None:
        rows.sort(key=key, reverse=(direction == 'desc'))
    else:
        rows.sort(key=lambda r: (r['pp_code'], r['akun']))
    return rows


def tf_program_rows(ctx, *, search='', sort='', direction='asc'):
    return program_rows(ctx, prefixes=('TF-',), search=search, sort=sort, direction=direction)


def research_object_rows(ctx, *, search='', sort='', direction='asc'):
    """NTF Research main rows: ONE row per research/hibah objek (Project
    prefix RS-) per PP. Figures from mapped GL like TF programs."""
    return program_rows(ctx, prefixes=('RS-',), search=search, sort=sort, direction=direction)


def service_object_rows(ctx, *, search='', sort='', direction='asc'):
    """NTF Project service/layanan objek (prefix SRV-) rows, merged below
    with contract projects by project_rows when needed."""
    return program_rows(ctx, prefixes=('SRV-',), search=search, sort=sort, direction=direction)


def program_rows(ctx, *, prefixes=('TF-',), search='', sort='', direction='asc'):
    """Generic objek rows: ONE row per Project whose number starts with one
    of `prefixes` (TF- / RS- / SRV-), per PP.

    GL rows are attached via GLProjectMapping (PP+NAME, longest match).
    Figures:
      nilai (Nilai Proyek)    = project.project_value (RKA allocation)
      total_pendapatan        = mapped GL lifetime up to ctx period
      pendapatan_berjalan     = mapped GL YTD (Jan..selected month)
    Different PPs/objects are NEVER merged.
    """
    from django.db.models import Q as _Q
    if prefixes:
        q = _Q(project_number__startswith=prefixes[0])
        for pfx in prefixes[1:]:
            q |= _Q(project_number__startswith=pfx)
        qs = Project.objects.filter(is_active=True).filter(q)
    else:
        qs = Project.objects.filter(is_active=True)
    qs = qs.select_related('pp__organization_unit', 'organization_unit')
    if ctx.organization is not None:
        qs = qs.filter(pp__organization_unit=ctx.organization)
    if ctx.pp is not None:
        qs = qs.filter(pp=ctx.pp)
    if ctx.revenue_account is not None:
        qs = qs.filter(
            gl_mappings__ledger__revenue_account=ctx.revenue_account
        ).distinct()

    q = (search or '').strip().lower()
    rows = []
    for project in qs.distinct().order_by('pp__pp_code', 'project_number'):
        pp_label = project.pp.pp_code if project.pp else ''
        org_name = (project.pp.organization_unit.name
                    if project.pp and project.pp.organization_unit else '')
        accounts = project_accounts(project)
        if not accounts:
            # placeholder project with no GL account: hide unless it has value
            if (project.project_value or 0) <= 0:
                continue
            accounts = [{'code': '', 'name': project.project_name, 'mode': 'HISTORICAL'}]
        per_acc = project_account_totals(project, ctx.year, ctx.month)
        # Project-level revenue up to the selected period (ALL accounts of the
        # project): drives the progress bar so multi-account rows share ONE
        # project progress (spec: progress = project total revenue / value).
        proj_total = sum((t.get('lifetime') or ZERO) for t in per_acc.values())
        for acc in accounts:
            code, name, mode = acc['code'], acc['name'], acc['mode']
            if q and q not in (project.project_name or '').lower()                 and q not in (pp_label or '').lower()                 and q not in (org_name or '').lower()                 and q not in (code or '').lower()                 and q not in (name or '').lower():
                continue
            totals = per_acc.get(code, {'lifetime': ZERO, 'ytd': ZERO, 'month': ZERO})
            rows.append({
                'project': project,
                'mode': 'tf_program',
                'tahun': ctx.year,
                'bulan': ctx.month,
                'month': ctx.month,
                'unit': org_name,
                'no_proyek': project.project_number,
                'pp_code': pp_label,
                'organization': org_name,
                'nama': name or '-',              # Nama Akun column
                'nama_proyek': project.project_name,  # Nama Proyek column
                'akun': code,
                'akun_nama': name or '',
                'nilai': project.project_value,
                # Column semantics (per spec):
                #   Pendapatan Diakui = selected MONTH revenue only
                #   Total Pendapatan  = lifetime recognized up to period end
                #   (YTD kept in realisasi_ytd for reference/tooltips)
                'total_pendapatan': totals['lifetime'],
                'pendapatan_berjalan': totals['month'],
                'realisasi_bulan': totals['month'],
                'realisasi_ytd': totals['ytd'],
                'detail_mode': mode,
                'project_total_pendapatan': proj_total,
                'detail_params': {'pp': pp_label, 'account': code, 'project_id': project.pk},
            })

    col_map = {
        'tahun': lambda r: r['tahun'],
        'bulan': lambda r: r['bulan'],
        'unit': lambda r: r['unit'].lower(),
        'no_proyek': lambda r: r['no_proyek'],
        'kode_pp': lambda r: r['pp_code'],
        'organization': lambda r: r['organization'].lower(),
        'nama': lambda r: r['nama'].lower(),
        'nama_proyek': lambda r: r['nama_proyek'].lower(),
        'akun': lambda r: r['akun'].lower(),
        'nilai': lambda r: r['nilai'] or ZERO,
        'total_pendapatan': lambda r: r['total_pendapatan'],
        'pendapatan_berjalan': lambda r: r['pendapatan_berjalan'],
    }
    key = col_map.get(sort)
    if key is not None:
        rows.sort(key=key, reverse=(direction == 'desc'))
    else:
        rows.sort(key=lambda r: r['no_proyek'])
    return rows


# --------------------------------------------------------------------------
# TF / NTF Research presented with the SAME table shape as NTF Project.
# These categories have no Project Master, so each row stays at the
# (PP x Revenue Account) grain and the "project" columns are adapted:
#   Nama Proyek  = nama akun pendapatan (label disesuaikan)
#   No Proyek    = ''   Unit = ''   Nilai Proyek = ''
# Expand shows the underlying GL transactions for the PP x Account.
# --------------------------------------------------------------------------
def account_category_rows(ctx, category_code, *, search='', sort='', direction='asc'):
    from django.db.models import Q as _Q, Sum as _Sum
    from finance.models import RevenueLedger as _RL

    base = _RL.objects.filter(
        revenue_account__isnull=False,
        revenue_account__revenue_category__code=category_code,
    )
    if ctx.organization is not None:
        base = base.filter(pp__organization_unit=ctx.organization)
    if ctx.pp is not None:
        base = base.filter(pp=ctx.pp)
    if ctx.revenue_account is not None:
        base = base.filter(revenue_account=ctx.revenue_account)

    # scope: all periods up to (year, month) => "lifetime-to-date"; YTD subset
    up_to = _Q(period__year__lt=ctx.year) | _Q(period__year=ctx.year, period__month__lte=ctx.month)
    life_base = base.filter(up_to)
    ytd_base = base.filter(period__year=ctx.year, period__month__lte=ctx.month)

    def agg(qs):
        return qs.values(
            'pp_id', 'pp__pp_code', 'pp__organization_unit__name',
            'revenue_account__account_code', 'revenue_account__account_name',
        ).annotate(credit=_Sum('credit'), debit=_Sum('debit'))

    life = agg(life_base)
    ytd = agg(ytd_base)
    life_map = {(r['pp_id'], r['revenue_account__account_code']): (r['credit'] or ZERO) - (r['debit'] or ZERO) for r in life}
    ytd_map = {(r['pp_id'], r['revenue_account__account_code']): (r['credit'] or ZERO) - (r['debit'] or ZERO) for r in ytd}
    info_map = {(r['pp_id'], r['revenue_account__account_code']): r for r in life}

    rows = []
    for key, total in life_map.items():
        info = info_map[key]
        unit_label = 'Tuition Fee' if category_code == 'TF' else 'Penelitian'
        rows.append({
            'mode': 'account',
            'tahun': ctx.year,
            'bulan': ctx.month,
            # No real project exists for TF/Research: expose the PP+account
            # pair as the row identifier and a functional unit label so the
            # columns are never empty.
            'unit': unit_label,
            'no_proyek': f"{info['pp__pp_code']}-{info['revenue_account__account_code']}",
            'pp_code': info['pp__pp_code'] or '',
            'organization': info['pp__organization_unit__name'] or '',
            'nama': info['revenue_account__account_name'] or '',   # disesuaikan = nama akun
            'akun': info['revenue_account__account_code'] or '',
            'akun_nama': info['revenue_account__account_name'] or '',
            'nilai': None,                                          # no project value
            'total_pendapatan': total,
            'pendapatan_berjalan': ytd_map.get(key, ZERO),
            'detail_params': {'pp': info['pp__pp_code'], 'account': info['revenue_account__account_code']},
        })

    q = (search or '').strip().lower()
    if q:
        rows = [r for r in rows
                if q in r['organization'].lower() or q in r['pp_code'].lower()
                or q in r['akun'].lower() or q in r['nama'].lower()]

    col_map = {
        'tahun': lambda r: r['tahun'],
        'bulan': lambda r: r['bulan'],
        'unit': lambda r: r['unit'],
        'no_proyek': lambda r: r['no_proyek'],
        'kode_pp': lambda r: r['pp_code'],
        'organization': lambda r: r['organization'].lower(),
        'nama': lambda r: r['nama'].lower(),
        'nama_proyek': lambda r: r['nama_proyek'].lower(),
        'akun': lambda r: r['akun'],
        'nilai': lambda r: r['nilai'] or ZERO,
        'total_pendapatan': lambda r: r['total_pendapatan'],
        'pendapatan_berjalan': lambda r: r['pendapatan_berjalan'],
    }
    key = col_map.get(sort)
    if key is not None:
        rows.sort(key=key, reverse=(direction == 'desc'))
    else:
        rows.sort(key=lambda r: r['total_pendapatan'], reverse=True)
    return rows


def account_gl_history(ctx, pp_code, account_code):
    """GL rows for one (PP x Account) within the selected context year,
    up to the selected month (YTD) — expand panel. Never crosses years."""
    from finance.models import RevenueLedger as _RL
    qs = _RL.objects.filter(
        pp__pp_code=pp_code, revenue_account__account_code=account_code,
        period__year=ctx.year, period__month__lte=ctx.month,
    ).select_related('period', 'revenue_account').order_by('-posting_date', '-id')
    return [{
        'date': r.posting_date,
        'voucher': r.voucher_number,
        'document': r.document_number,
        'description': r.description_raw,
        'pp_code': r.pp.pp_code if r.pp else (r.pp_code_raw or ''),
        'organization': r.pp.organization_unit.name if r.pp and r.pp.organization_unit else '',
        'account_code': r.revenue_account.account_code if r.revenue_account else r.account_code_raw,
        'account_name': r.revenue_account.account_name if r.revenue_account else r.account_name_raw,
        'amount': _net(r),
    } for r in qs]


def models_q_year_month_lte(ctx):
    from django.db.models import Q
    return Q(period__year__lt=ctx.year) | Q(period__year=ctx.year, period__month__lte=ctx.month)






def tf_account_pp_gl(ctx, pp_code, account_code, month):
    """GL transactions of ONE (PP x Account x Month) — authoritative detail
    behind a Data TF main row. NEVER crosses PP: only rows of this exact PP,
    of this revenue account, in this period."""
    from finance.models import RevenueLedger as _RL
    qs = _RL.objects.filter(
        pp__pp_code=pp_code,
        revenue_account__account_code=account_code,
        period__year=ctx.year, period__month=month,
    ).select_related('period', 'revenue_account', 'pp', 'pp__organization_unit')
    rows = list(qs.order_by('posting_date', 'id'))
    return [{
        'date': r.posting_date,
        'voucher': r.voucher_number,
        'document': r.document_number,
        'description': r.description_raw,
        'pp_code': r.pp.pp_code if r.pp else (r.pp_code_raw or ''),
        'organization': r.pp.organization_unit.name if r.pp and r.pp.organization_unit else '',
        'account_code': r.revenue_account.account_code if r.revenue_account else r.account_code_raw,
        'account_name': r.revenue_account.account_name if r.revenue_account else r.account_name_raw,
        'amount': _net(r),
    } for r in rows]


def account_month_gl(ctx, account_code, month, activity=None):
    """GL rows of ONE account in ONE month (expand panel of the TF table).

    For activity-split accounts pass `activity` to list only the
    GL rows of that paid activity (e.g. 'Seminar'); account-level rows pass
    no activity and receive every GL row of the month.
    """
    from finance.models import RevenueLedger as _RL
    qs = _RL.objects.filter(
        revenue_account__account_code=account_code,
        period__year=ctx.year, period__month=month,
    ).select_related('period', 'revenue_account', 'pp', 'pp__organization_unit')
    if ctx.organization is not None:
        qs = qs.filter(pp__organization_unit=ctx.organization)
    if ctx.pp is not None:
        qs = qs.filter(pp=ctx.pp)
    if activity:
        qs = qs.filter(description_raw__icontains=activity)
    rows = list(qs.order_by('pp__pp_code', 'posting_date', 'id'))
    return [{
        'date': r.posting_date,
        'voucher': r.voucher_number,
        'document': r.document_number,
        'description': r.description_raw,
        'pp_code': r.pp.pp_code if r.pp else (r.pp_code_raw or ''),
        'organization': r.pp.organization_unit.name if r.pp and r.pp.organization_unit else '',
        'account_code': r.revenue_account.account_code if r.revenue_account else r.account_code_raw,
        'account_name': r.revenue_account.account_name if r.revenue_account else r.account_name_raw,
        'amount': _net(r),
    } for r in rows]
