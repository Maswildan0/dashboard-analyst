"""Account classification and description normalization for GL rows.

Rules:
- Classification is by account_code against RevenueAccount master ONLY.
  There is deliberately NO catch-all `else -> NTF_PROJECT`.
- Unknown/expired account => classification UNMAPPED (revenue_account=None).
- Normalization never touches the raw description; it produces a
  cleaned copy used for matching/search.
"""
import re
import unicodedata

_GENERIC_WORDS = {
    'pendapatan', 'penerimaan', 'pengakuan', 'realisasi', 'termin', 'tahap',
    'pelunasan', 'proyek', 'project', 'pembayaran', 'jasa', 'pekerjaan',
    'kontrak', 'tahun', 'bulan', 'sebesar', 'sbb', 'sd', 's/d', 'dll', 'unit',
    'progress', 'invoice', 'faktur', 'no', 'nomor', 'tanggal',
}

_PUNCT_RE = re.compile(r'[^\w\s]', re.UNICODE)
_SPACE_RE = re.compile(r'\s+')


def normalize_description(raw):
    """Lowercase, strip diacritics, trim, collapse spaces, drop punctuation.

    Generic accounting words are removed so 'Termin 1 Proyek X' and
    'X project stage one' can still match on the distinctive core.
    """
    if not raw:
        return ''
    text = unicodedata.normalize('NFKD', raw)
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = _PUNCT_RE.sub(' ', text)
    text = _SPACE_RE.sub(' ', text).strip()
    tokens = [t for t in text.split(' ') if t and t not in _GENERIC_WORDS]
    return ' '.join(tokens)


def classify_account(account_code, valid_on=None):
    """Return (RevenueAccount|None, status).

    status: 'MAPPED' | 'UNMAPPED'. Expired (valid_to < valid_on) counts as
    UNMAPPED so GL is never force-fitted into a category.
    """
    from datetime import date
    from finance.models import RevenueAccount

    if not account_code:
        return None, 'UNMAPPED'
    qs = RevenueAccount.objects.filter(account_code=str(account_code).strip(), is_active=True)
    if valid_on is None:
        valid_on = date.today()
    account = qs.filter(models_or_valid(valid_on)).first() if hasattr(qs, 'models_or_valid') else None
    # explicit validity window filter (null = always valid)
    from django.db.models import Q
    account = qs.filter(Q(valid_from__isnull=True) | Q(valid_from__lte=valid_on),
                        Q(valid_to__isnull=True) | Q(valid_to__gte=valid_on)).first()
    return (account, 'MAPPED') if account else (None, 'UNMAPPED')
