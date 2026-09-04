"""SIMKUG API adapter.

Environment variables only (never commit keys):
    SIMKUG_API_URL   e.g. https://simkug.example/api/v1
    SIMKUG_API_KEY

Three feed families, deliberately kept separate (they never merge into one
raw table):
    fetch_general_ledger(start, end)  -> actual revenue (authoritative)
    fetch_ntf_report(year, month)     -> project metadata (NOT authoritative
                                         for revenue amounts)
    fetch_revenue_rka(year)           -> RKA target (authoritative)

Each returns an iterable of dicts with the documented raw column names.
A stub (live=False) mode returns deterministic sample rows so the rest of
the pipeline can be built and tested before the real endpoint exists.
"""
import os
from datetime import date, timedelta

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


def _base_url():
    return (os.environ.get('SIMKUG_API_URL') or '').rstrip('/')


def _headers():
    key = os.environ.get('SIMKUG_API_KEY') or ''
    headers = {'Accept': 'application/json'}
    if key:
        headers['Authorization'] = f'Bearer {key}'
    return headers


def live_enabled():
    return bool(os.environ.get('SIMKUG_API_URL')) and bool(os.environ.get('SIMKUG_API_KEY'))


def _get(path, params):
    if requests is None:  # pragma: no cover
        raise RuntimeError('requests is not installed')
    resp = requests.get(f'{_base_url()}{path}', params=params, headers=_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json()


# --------------------------------------------------------------------------
# Feed stubs (deterministic) used while SIMKUG_API_URL is not configured.
# --------------------------------------------------------------------------
def _stub_gl_rows(start, end):
    """Deterministic GL-style rows: a few accounts/PPs across the range."""
    from finance.models import PPMaster, RevenueAccount
    pps = list(PPMaster.objects.filter(is_active=True).values_list('pp_code', flat=True)[:6]) or ['9130', '9106', '9114']
    accounts = list(RevenueAccount.objects.filter(is_active=True).values_list('account_code', 'account_name', 'revenue_category__code')) or [
        ('4140101', 'Pendapatan Kerja Sama Proyek', 'NTF_PROJECT'),
        ('4130101', 'Pendapatan Jasa Penelitian', 'NTF_RESEARCH'),
        ('4121135', 'Pendapatan Pddk Pelatihan, Seminar, Workshop, dan Konferensi', 'TF'),
    ]
    rows = []
    day = start
    idx = 0
    while day <= end:
        acc_code, acc_name, cat = accounts[idx % len(accounts)]
        pp = pps[(idx * 2 + 1) % len(pps)]
        nominal = (idx % 5 + 1) * 50_000_000  # 50..250jt per line
        # Revenue recognition posts to credit; debit reserved for the rare
        # reversal/adjustment so 'net = credit - debit' stays meaningful.
        credit = nominal
        debit = nominal if idx % 7 == 0 else 0
        rows.append({
            'transaction_id': f'GL-{day:%Y%m%d}-{idx:04d}',
            'line_id': f'L-{idx:04d}',
            'posting_date': day.isoformat(),
            'voucher_number': f'V-{day:%m}{idx:03d}',
            'document_number': f'DOC-{idx:05d}',
            'account_code': acc_code,
            'account_name': acc_name,
            'description': f'Termin {idx % 3 + 1} {acc_name} {pp}',
            'pp_code': pp,
            'debit': debit,
            'credit': credit,
            'balance': nominal,
            'source_updated_at': day.isoformat(),
        })
        day += timedelta(days=1)
        idx += 1
    return rows


def _stub_ntf_rows(year, month):
    """Deterministic NTF report rows -> project metadata (NOT authoritative
    revenue; authoritative recognition comes from mapped GL)."""
    rows = [
        {'project_number': 'P-9130-001', 'pp_code': '9130', 'contract_code': 'CT-2026-001',
         'project_name': 'Smart Campus Telkom University', 'unit': 'Divisi Digital',
         'organization': 'RI-CCSL', 'project_value': 5_000_000_000,
         'total_recognized': 0, 'current_year_recognized': 0},
        {'project_number': 'P-9106-001', 'pp_code': '9106', 'contract_code': 'CT-2026-002',
         'project_name': 'Fiber Optik Kampus', 'unit': 'Divisi Telekom',
         'organization': 'RI-CCSL', 'project_value': 3_200_000_000,
         'total_recognized': 0, 'current_year_recognized': 0},
        {'project_number': 'P-2302-001', 'pp_code': '2302', 'contract_code': 'CT-2026-003',
         'project_name': 'Pembangunan ATCS Bandung', 'unit': 'Divisi Digital',
         'organization': 'DIREKTORAT ASUS', 'project_value': 1_500_000_000,
         'total_recognized': 0, 'current_year_recognized': 0},
    ]
    return rows


def _stub_rka_rows(year):
    from finance.models import PPMaster, RevenueAccount
    pps = list(PPMaster.objects.filter(is_active=True).values_list('pp_code', flat=True)[:6]) or ['9130']
    accounts = list(RevenueAccount.objects.filter(is_active=True).values_list('account_code', flat=True)) or ['4140101']
    rows = []
    for pp in pps:
        for acc in accounts:
            annual = 1_200_000_000
            monthly = [annual // 12] * 12
            monthly[-1] = annual - sum(monthly[:-1])
            rows.append({
                'year': year,
                'pp_code': pp,
                'account_code': acc,
                'annual_budget': annual,
                'monthly_phasing': monthly,
            })
    return rows


def fetch_general_ledger(start=None, end=None, *, force_stub=False):
    """Yield GL rows between start and end (inclusive dates)."""
    start = start or date(date.today().year, 1, 1)
    end = end or start.replace(day=28)
    if live_enabled() and not force_stub:
        return _get('/general-ledger', {'start': start.isoformat(), 'end': end.isoformat()})
    return _stub_gl_rows(start, end)


def fetch_ntf_report(year=None, month=None, *, force_stub=False):
    year = year or date.today().year
    month = month or date.today().month
    if live_enabled() and not force_stub:
        return _get('/ntf-report', {'year': year, 'month': month})
    return _stub_ntf_rows(year, month)


def fetch_revenue_rka(year=None, *, force_stub=False):
    year = year or date.today().year
    if live_enabled() and not force_stub:
        return _get('/rka', {'year': year})
    return _stub_rka_rows(year)
