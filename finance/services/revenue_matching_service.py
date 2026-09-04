"""GL <-> Project matching.

One PP can map to many projects; PP alone only narrows candidates. Matching
combines PP, normalized description vs project name/aliases, temporal
continuity, and amount consistency (supporting evidence).

Unmatched GL revenue is NEVER dropped from totals: it simply has no mapping
row. Data quality surfaces the gap (mapped vs unmapped).
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Q

from finance.models import (
    GLProjectMapping,
    Project,
    ProjectAlias,
    RevenueLedger,
)

ZERO = Decimal('0')

MATCH_METHODS = {
    'PP_ONLY': 0.30,
    'NAME_EXACT': 0.95,
    'ALIAS_EXACT': 0.90,
    'NAME_FUZZY': 0.70,
    'TEMPORAL': 0.60,
    'AMOUNT': 0.50,
}


def _normalize(s):
    from finance.services.account_classification import normalize_description
    return normalize_description(s)


def _token_similarity(a, b):
    """Simple Jaccard over token sets."""
    if not a or not b:
        return 0.0
    sa = set(a.split()); sb = set(b.split())
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def _core_tokens(name):
    return set(_normalize(name).split())


def _candidate_projects(ledger):
    """PP-scoped candidates + previous-match memory."""
    qs = Project.objects.filter(is_active=True)
    if ledger.pp is not None:
        qs = qs.filter(Q(pp=ledger.pp) | Q(project_number__icontains=ledger.pp_code_raw))
    # temporal: prefer projects seen around same month previously
    return qs


def score_ledger(ledger, project):
    """Score one (ledger, project) pair in [0,1]."""
    score = 0.0
    # PP overlap is required-ish; brings base
    if ledger.pp is not None and project.pp is not None and ledger.pp_id == project.pp_id:
        score += MATCH_METHODS['PP_ONLY']

    desc = _normalize(ledger.description_normalized or ledger.description_raw)
    name = _normalize(project.project_name)
    if desc and name:
        exact = desc == name
        if exact:
            score += MATCH_METHODS['NAME_EXACT']
        else:
            sim = _token_similarity(desc, name)
            score += MATCH_METHODS['NAME_FUZZY'] * sim

        # aliases
        for alias in project.aliases.all():
            a = _normalize(alias.alias_normalized or alias.alias_raw)
            if a and a == desc:
                score += MATCH_METHODS['ALIAS_EXACT']
                break

    # temporal memory: has this project been matched near this period?
    same_month = project.monthly_snapshots.filter(
        period__month=(ledger.period.month if ledger.period else 1))
    if same_month.exists():
        score += MATCH_METHODS['TEMPORAL']

    # amount consistency as supporting evidence (soft)
    amount = abs(ledger.credit - ledger.debit)
    if amount and project.project_value:
        ratio = amount / project.project_value
        if Decimal('0.01') <= ratio <= Decimal('0.95'):
            score += MATCH_METHODS['AMOUNT'] * 0.4
    return float(min(score, 1.0))


def classify_score(score):
    if score >= 0.85:
        return 'AUTO_MATCHED'
    if score >= 0.55:
        return 'NEEDS_REVIEW'
    return 'UNMATCHED'


def auto_match_ledger(ledger):
    """Find best project for one ledger row; create mapping row."""
    if GLProjectMapping.objects.filter(ledger=ledger).exists():
        return GLProjectMapping.objects.get(ledger=ledger)
    candidates = _candidate_projects(ledger)
    best = None; best_score = 0.0
    for project in candidates.select_related('pp').prefetch_related('aliases')[:50]:
        sc = score_ledger(ledger, project)
        if sc > best_score:
            best_score = sc; best = project
    mapping = GLProjectMapping.objects.create(
        ledger=ledger,
        project=best,
        allocated_amount=(abs(ledger.credit - ledger.debit) if best else None),
        match_method=('PP_ONLY+NAME' if best else 'NONE'),
        match_confidence=(Decimal(str(round(best_score, 2))) if best else None),
        match_status=classify_score(best_score),
    )
    # learn alias on strong match
    if best is not None and best_score >= 0.85 and ledger.description_raw:
        norm = _normalize(ledger.description_raw)
        if norm:
            ProjectAlias.objects.get_or_create(
                project=best,
                alias_normalized=norm,
                defaults={'alias_raw': ledger.description_raw[:300], 'source': 'GL',
                          'is_verified': best_score >= 0.95},
            )
    return mapping


def run_matching(period):
    """Match all UNMATCHED-ledger rows of a period that have no mapping yet."""
    created = 0
    with transaction.atomic():
        ledgers = RevenueLedger.objects.filter(period=period).exclude(
            id__in=GLProjectMapping.objects.values('ledger_id'))
        for ledger in ledgers.iterator(chunk_size=500):
            auto_match_ledger(ledger)
            created += 1
    return created


def review_stats(period=None):
    """Mapped / unmatched totals for data-quality panel."""
    base = GLProjectMapping.objects
    if period is not None:
        base = base.filter(ledger__period=period)
    from django.db.models import Sum
    mapped = base.exclude(match_status='UNMATCHED')
    mapped_amount = mapped.aggregate(s=Sum('allocated_amount'))['s'] or ZERO
    # unmapped = ledger rows with no mapping or UNMATCHED status
    from finance.models import RevenueLedger as RL
    qs = RL.objects.all()
    if period is not None:
        qs = qs.filter(period=period)
    total_amount = ZERO
    for row in qs.only('credit', 'debit').iterator(chunk_size=1000):
        total_amount += (row.credit - row.debit)
    return {
        'mapped_amount': mapped_amount,
        'total_amount': total_amount,
        'unmapped_amount': total_amount - mapped_amount,
        'mapped_ratio': (mapped_amount / total_amount * 100) if total_amount else None,
    }