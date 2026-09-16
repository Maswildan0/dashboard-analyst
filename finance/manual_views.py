"""HTTP endpoints for manual revenue (create / edit / void / restore / adjust).

Every write endpoint is POST-only, CSRF-protected (Django's CsrfViewMiddleware
is enabled for the project) and permission-gated server-side through
`finance.permissions`. Templates may hide a control, but a direct POST without
the matching permission still fails with 403 and a message — never silently.

Failure contract (all endpoints answer JSON):
    {'ok': False, 'message': ..., 'field': ...} with 400 (validation / period
    lock) or 403 (permission) so the client can surface a field-level error and
    keep the row it was working on (no optimistic removal, §52).
"""
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from .models import FinancialPeriod, ManualRevenueEntry, PPMaster, Project, RevenueAccount
from .permissions import allowed, capabilities, require, require_authenticated
from .services import manual_revenue as mr
from .services.revenue_context import RevenueContext


# ---------------------------------------------------------------------------
# Shared request helpers
# ---------------------------------------------------------------------------
def _error(message, *, field=None, status=400):
    return JsonResponse({'ok': False, 'message': message, 'field': field}, status=status)


def _ok(message, **extra):
    return JsonResponse({'ok': True, 'message': message, **extra})


def _resolve_period(request):
    """FinancialPeriod from posted year/month (never a client-supplied pk)."""
    raw = (request.POST.get('period') or '').strip()
    year = month = None
    if raw and '-' in raw:
        head, _, tail = raw.partition('-')
        year, month = head, tail
    year = year or request.POST.get('year')
    month = month or request.POST.get('month')
    try:
        year, month = int(year), int(month)
    except (TypeError, ValueError):
        raise mr.ManualRevenueError('Periode wajib dipilih.', field='period')
    period = FinancialPeriod.objects.filter(year=year, month=month).first()
    if period is None:
        raise mr.ManualRevenueError(
            f'Periode {year}-{month:02d} belum terdaftar.', field='period')
    return period


def _posted_master(request):
    """Resolve the master rows the posted form points at."""
    return mr.resolve_master(
        category_code=request.POST.get('revenue_type'),
        organization_id=request.POST.get('organization'),
        pp_code=request.POST.get('pp'),
        account_code=request.POST.get('revenue_account'),
        project_id=request.POST.get('project') or None,
    )


def _guarded(view):
    """Run a write view, mapping domain/permission errors onto JSON."""
    def wrapper(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except mr.ManualRevenueError as exc:
            return _error(exc.message, field=exc.field, status=exc.status)
        except PermissionDenied as exc:
            return _error(str(exc), status=403)
    wrapper.__name__ = view.__name__
    wrapper.__doc__ = view.__doc__
    return wrapper


def guards_permission(action):
    """POST-only + permission + JSON error mapping for one manual action."""
    def decorator(view):
        @require_POST
        @_guarded
        def wrapper(request, *args, **kwargs):
            require(request.user, action)
            return view(request, *args, **kwargs)
        wrapper.__name__ = view.__name__
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Capabilities (template contract: allowed_revenue_type / page_mode / perms)
# ---------------------------------------------------------------------------
def manual_context(request, *, page_mode, allowed_revenue_types):
    """The entire page-specific manual-entry context (§3).

    A page contributes only its mode and allowed revenue types; the shared
    partials and JS derive everything else from this dict, so Data Revenue,
    Data TF, NTF Research and NTF Project share ONE implementation.
    """
    return {
        'page_mode': page_mode,
        'allowed_revenue_types': list(allowed_revenue_types),
        'locked_revenue_type': allowed_revenue_types[0] if len(allowed_revenue_types) == 1 else '',
        'perms': capabilities(request.user),
    }


# ---------------------------------------------------------------------------
# Write endpoints
# ---------------------------------------------------------------------------
@guards_permission('create')
def create(request):
    """Create a POSTED MANUAL recognition (mode A new object / mode B termin)."""
    period = _resolve_period(request)
    master = _posted_master(request)
    amount = mr.parse_amount(request.POST.get('amount'))
    tx_date = mr.parse_date(request.POST.get('transaction_date'))
    project_value = mr.parse_project_value(request.POST.get('project_value'))
    entry = mr.create_entry(
        period=period,
        category=master['category'],
        organization=master['organization'],
        pp=master['pp'],
        account=master['account'],
        project=master['project'],
        transaction_date=tx_date,
        amount=amount,
        evidence_number=request.POST.get('evidence_number', ''),
        document_number=request.POST.get('document_number', ''),
        description=request.POST.get('description', ''),
        source_type='MANUAL',
        user=request.user,
        project_name=request.POST.get('project_name', ''),
        project_number=request.POST.get('project_number', ''),
        project_value=project_value,
    )
    return _ok('Data manual berhasil disimpan.', entry_id=entry.pk,
               project_id=entry.project_id)


@guards_permission('edit')
def edit(request, entry_id):
    """Edit transaction fields of a MANUAL POSTED row (§18, §19)."""
    entry = _get_entry(entry_id)
    amount = None
    if request.POST.get('amount') is not None:
        amount = mr.parse_amount(request.POST.get('amount'))
    tx_date = None
    if request.POST.get('transaction_date') is not None:
        tx_date = mr.parse_date(request.POST.get('transaction_date'))
    mr.update_entry(
        entry,
        amount=amount,
        transaction_date=tx_date,
        evidence_number=request.POST.get('evidence_number'),
        document_number=request.POST.get('document_number'),
        description=request.POST.get('description'),
        project_name=request.POST.get('project_name'),
        project_number=request.POST.get('project_number'),
        project_value=mr.parse_project_value(request.POST.get('project_value')),
        user=request.user,
    )
    return _ok('Perubahan berhasil disimpan.', entry_id=entry.pk)


@guards_permission('void')
def void(request, entry_id):
    """Soft delete (VOID) with a mandatory reason (§20, §21)."""
    entry = _get_entry(entry_id)
    reason = mr.parse_choice(
        request.POST.get('void_reason'), mr.VOID_REASONS,
        field='void_reason', label='Alasan penghapusan')
    if reason == 'Lainnya':
        other = (request.POST.get('void_reason_other') or '').strip()
        if not other:
            raise mr.ManualRevenueError(
                'Alasan penghapusan wajib diisi untuk pilihan Lainnya.',
                field='void_reason_other')
        reason = other
    mr.void_entry(entry, reason=reason, user=request.user)
    return _ok('Data berhasil dihapus dari data aktif. Riwayat tetap tersimpan.',
               entry_id=entry.pk)


@guards_permission('restore')
def restore(request, entry_id):
    """VOID -> POSTED while the target period is still OPEN (§23, §24)."""
    entry = _get_entry(entry_id)
    mr.restore_entry(entry, user=request.user)
    return _ok('Data berhasil dipulihkan.', entry_id=entry.pk)


@guards_permission('adjustment')
def adjustment(request):
    """Correct an IMPORTED source by adding a new ADJUSTMENT row (§27, §28)."""
    period = _resolve_period(request)
    master = _posted_master(request)
    amount = mr.parse_amount(request.POST.get('amount'), label='Nominal Koreksi')
    tx_date = mr.parse_date(request.POST.get('transaction_date'))
    reason = mr.parse_choice(
        request.POST.get('reason'), mr.ADJUSTMENT_REASONS,
        field='reason', label='Alasan koreksi')
    if reason == 'Lainnya':
        other = (request.POST.get('reason_other') or '').strip()
        if not other:
            raise mr.ManualRevenueError(
                'Alasan koreksi wajib diisi untuk pilihan Lainnya.', field='reason_other')
        reason = other
    reference = mr.resolve_reference_ledger(
        request.POST.get('reference_ledger'), account=master['account'])
    entry = mr.create_entry(
        period=period,
        category=master['category'],
        organization=master['organization'],
        pp=master['pp'],
        account=master['account'],
        project=master['project'],
        transaction_date=tx_date,
        amount=amount,
        evidence_number=request.POST.get('evidence_number', ''),
        document_number=request.POST.get('document_number', ''),
        description=request.POST.get('description', ''),
        source_type='ADJUSTMENT',
        reference_ledger=reference,
        reason=reason,
        user=request.user,
    )
    return _ok('Koreksi berhasil dicatat.', entry_id=entry.pk)


def _get_entry(entry_id):
    return (ManualRevenueEntry.objects
            .select_related('period', 'project', 'pp', 'revenue_account',
                            'revenue_category', 'organization_unit')
            .filter(pk=entry_id).first()
            or _raise_missing())


def _raise_missing():
    raise mr.ManualRevenueError('Data manual tidak ditemukan.', status=404)


# ---------------------------------------------------------------------------
# Cascading option endpoints (§6) — masters come from the database
# ---------------------------------------------------------------------------
def option_pps(request):
    """PP options for one organization (cascading, §6)."""
    org_id = request.GET.get('org')
    qs = PPMaster.objects.filter(is_active=True).select_related('organization_unit')
    if org_id and str(org_id).isdigit():
        qs = qs.filter(organization_unit_id=int(org_id))
    return JsonResponse([{
        'value': p.pp_code,
        'label': p.pp_code,
        'org': p.organization_unit.name if p.organization_unit else '',
    } for p in qs.order_by('pp_code')], safe=False)


def option_accounts(request):
    """Revenue Account options for one revenue category (cascading, §6)."""
    qs = RevenueAccount.objects.filter(is_active=True).select_related('revenue_category')
    rtype = (request.GET.get('type') or '').strip().upper()
    if rtype:
        qs = qs.filter(revenue_category__code=rtype)
    elif request.GET.get('types'):
        codes = [c.strip().upper() for c in request.GET['types'].split(',') if c.strip()]
        qs = qs.filter(revenue_category__code__in=codes)
    return JsonResponse([{
        'value': a.account_code,
        'label': f'{a.account_code} · {a.account_name}',
        'type': a.revenue_category.code,
        'mode': a.detail_history_mode,
    } for a in qs.order_by('account_code')], safe=False)


def option_projects(request):
    """Projects of one PP + category, for MODE B (termin to an existing one).

    Only projects the operator may key against are offered: those whose PP and
    account already agree with the selection (1 project = 1 PP = 1 account).
    """
    pp_code = (request.GET.get('pp') or '').strip()
    rtype = (request.GET.get('type') or '').strip().upper()
    account_code = (request.GET.get('account') or '').strip()
    qs = Project.objects.filter(is_active=True).select_related('pp')
    if pp_code:
        qs = qs.filter(pp__pp_code=pp_code)
    if rtype or account_code:
        mapped = Q(gl_mappings__ledger__revenue_account__isnull=False)
        if account_code:
            mapped &= Q(gl_mappings__ledger__revenue_account__account_code=account_code)
        if rtype:
            mapped &= Q(gl_mappings__ledger__revenue_account__revenue_category__code=rtype)
        manual = Q(manual_entries__status__in=['POSTED', 'VOID'])
        if account_code:
            manual &= Q(manual_entries__revenue_account__account_code=account_code)
        if rtype:
            manual &= Q(manual_entries__revenue_account__revenue_category__code=rtype)
        qs = qs.filter(mapped | manual).distinct()
    projects = qs.order_by('project_number')[:200]
    return JsonResponse([{
        'value': p.pk,
        'number': p.project_number,
        'label': f'{p.project_number} · {p.project_name}'.strip(' ·'),
        'name': p.project_name,
        'value_amount': str(p.project_value),
        'source_type': p.source_type,
        'organization': p.organization_unit_id,
    } for p in projects], safe=False)


def option_ledger(request):
    """Imported GL rows an Adjustment may reference (§27) — read only."""
    qs = mr.editable_ledger_rows(
        account_code=(request.GET.get('account') or '').strip() or None,
        pp_code=(request.GET.get('pp') or '').strip() or None,
        project_id=_as_int(request.GET.get('project')),
    )
    return JsonResponse([{
        'value': r.pk,
        'label': f'{r.posting_date or r.period.period_start} · '
                 f'{r.voucher_number or "-"} · {_rp(r.credit - r.debit)}',
        'amount': str(r.credit - r.debit),
    } for r in qs.select_related('period')[:100]], safe=False)


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Read fragments (audit history, deleted data) — AJAX HTML
# ---------------------------------------------------------------------------
def history(request):
    """Audit timeline of one entry, or of every manual entry of one project."""
    require_authenticated(request.user)
    entry_id = request.GET.get('entry')
    project_id = request.GET.get('project')
    if entry_id and str(entry_id).isdigit():
        entry = ManualRevenueEntry.objects.filter(pk=int(entry_id)).first()
        if entry is None:
            return _error('Data manual tidak ditemukan.', status=404)
        audit_rows = mr.audit_events(entry)
        title = f'{entry.project.project_number or entry.project.project_name}'
        entry_count = 1
        first_id = entry.pk
    elif project_id and str(project_id).isdigit():
        project = Project.objects.filter(pk=int(project_id)).first()
        if project is None:
            return _error('Project tidak ditemukan.', status=404)
        # One timeline for the whole project: every entry's events plus its
        # own master changes, still oldest first (§32).
        audit_rows = mr.audit_events_for_project(project.pk)
        title = project.project_number or project.project_name
        entry_count = mr.posted_entries().filter(project=project).count() \
            + ManualRevenueEntry.objects.filter(project=project, status='VOID').count()
        first_id = None
    else:
        return _error('Riwayat tidak dapat ditentukan.', status=400)

    if not audit_rows:
        return JsonResponse({'ok': True, 'html': _empty_history(), 'title': title})
    events = [_history_event(event) for event in audit_rows]
    html = render_to_string('finance/revenue/_manual_history_fragment.html', {
        'events': events,
        'entry_id': first_id,
        'entry_count': entry_count,
    })
    return JsonResponse({'ok': True, 'html': html, 'title': title})


def _history_event(event):
    before = event.old_value or {}
    after = event.new_value or {}
    changes = [
        (label, _display(old, money), _display(new, money))
        for label, old, new, money in mr.audit_diff(before, after)
    ]
    return {
        'id': event.pk,
        'timestamp': event.timestamp.isoformat() if event.timestamp else '',
        'date': event.timestamp,
        'action': event.action,
        'user': (event.user.get_username() if event.user
                 else (event.new_value or {}).get('performed_by') or 'Sistem'),
        'reason': event.reason or '',
        'changes': changes,
        'after': after,
        'before': before,
    }


def _display(value, money):
    """Audit values are stored as strings; money renders as full rupiah."""
    if value is None or value == '':
        return '—'
    if money:
        return _rp(value)
    return str(value)


def _empty_history():
    return ('<div class="rm-empty">Belum ada riwayat perubahan untuk data ini.</div>')


def entries(request):
    """PROJECT master + its POSTED manual recognitions (§18).

    Both edit levels read from here: the project form (name / number / value)
    and the transaction list where each row carries its own Edit and Hapus.
    Only operator-owned POSTED rows are listed, so an imported source can never
    be selected for deletion.
    """
    require_authenticated(request.user)
    project_id = _as_int(request.GET.get('project'))
    if not project_id:
        return JsonResponse({'ok': True, 'entries': [], 'project': None})
    project = Project.objects.filter(pk=project_id).select_related('pp').first()
    if project is None:
        return _error('Project tidak ditemukan.', status=404)
    rows = (mr.posted_entries()
            .filter(project_id=project_id)
            .select_related('period', 'revenue_account')
            .order_by('-transaction_date', '-id'))
    return JsonResponse({
        'ok': True,
        'project': {
            'id': project.pk,
            'number': project.project_number,
            'name': project.project_name,
            'value': str(project.project_value),
            'value_text': _rp(project.project_value),
            'pp': project.pp.pp_code if project.pp else '',
            'source_type': project.source_type,
            # Only a MANUAL project may have its master metadata corrected;
            # an imported project's name/number/value stay read-only (§14).
            'can_edit_master': bool(project.source_type == 'MANUAL'
                                    and allowed(request.user, 'edit')),
            'is_manual_source': project.source_type == 'MANUAL',
        },
        'entries': [{
            'id': e.pk,
            'date': e.transaction_date.isoformat() if e.transaction_date else '',
            'date_text': e.transaction_date.strftime('%d %b %Y') if e.transaction_date else '—',
            'account': f'{e.revenue_account.account_code} {e.revenue_account.account_name}',
            'account_code': e.revenue_account.account_code,
            'amount': str(e.amount),
            'amount_text': _rp(e.amount),
            'description': e.description,
            'evidence_number': e.evidence_number,
            'document_number': e.document_number,
            'source_type': e.source_type,
            'period': str(e.period),
            'period_open': not e.period.is_closed,
            'can_edit': bool(not e.period.is_closed
                             and allowed(request.user, 'edit')
                             and e.source_type in ('MANUAL', 'ADJUSTMENT')),
            'can_void': bool(not e.period.is_closed and allowed(request.user, 'void')
                             and e.source_type in ('MANUAL', 'ADJUSTMENT')),
        } for e in rows],
    })


@guards_permission('edit')
def project_edit(request, project_id):
    """Update a MANUAL project's master metadata (name / number / value).

    Project-level edit is separate from transaction edit by design (§18): this
    endpoint never touches a recognition amount, and the transaction endpoint
    never touches the project master.
    """
    period = _resolve_period(request)
    mr.require_open(period)
    project = Project.objects.filter(pk=project_id).first()
    if project is None:
        raise mr.ManualRevenueError('Project tidak ditemukan.', status=404)
    mr.update_manual_project(
        project,
        project_name=request.POST.get('project_name'),
        project_number=request.POST.get('project_number'),
        project_value=mr.parse_project_value(request.POST.get('project_value')),
        user=request.user,
    )
    return _ok('Perubahan berhasil disimpan.', project_id=project.pk)


def deleted(request):
    """Deleted (VOID) manual rows relevant to the calling page (§22)."""
    require_authenticated(request.user)
    codes = [c.strip().upper() for c in (request.GET.get('types') or '').split(',') if c.strip()]
    rows = [_deleted_row(e, request.user) for e in mr.deleted_entries(category_codes=codes or None)]
    html = render_to_string('finance/revenue/_deleted_data_fragment.html', {
        'rows': rows,
        'can_restore': allowed(request.user, 'restore'),
    })
    return JsonResponse({'ok': True, 'html': html, 'count': len(rows)})


def _deleted_row(entry, user):
    deletable = entry.period.is_closed is False
    return {
        'id': entry.pk,
        'deleted_at': entry.voided_at,
        'jenis': entry.revenue_category.code,
        'pp': entry.pp.pp_code,
        'project': entry.project.project_name or entry.project.project_number,
        'project_number': entry.project.project_number,
        'account': f'{entry.revenue_account.account_code} {entry.revenue_account.account_name}',
        'amount': entry.amount,
        'amount_disp': _rp(entry.amount),
        'deleted_by': entry.voided_by.get_username() if entry.voided_by else '—',
        'reason': entry.void_reason or '—',
        'source_type': entry.source_type,
        'period': str(entry.period),
        'period_open': deletable,
        'can_restore': bool(deletable and allowed(user, 'restore')),
    }


def _rp(value):
    """Full rupiah. Audit snapshots store money as decimal strings
    ('55000000.00'), so parse through Decimal before formatting."""
    try:
        return 'Rp' + f'{int(Decimal(str(value))):,}'.replace(',', '.')
    except (TypeError, ValueError, InvalidOperation):
        return 'Rp0'


# ---------------------------------------------------------------------------
# Page wiring: the context every revenue table page adds for the action area
# ---------------------------------------------------------------------------
PAGE_MODES = {
    'data': ('DATA_REVENUE', ['TF', 'NTF_RESEARCH', 'NTF_PROJECT']),
    'tf': ('TF', ['TF']),
    'ntf_research': ('NTF_RESEARCH', ['NTF_RESEARCH']),
    'ntf_project': ('NTF_PROJECT', ['NTF_PROJECT']),
}


def page_context(request, page):
    """Context for the shared action area / modals / JS on one revenue page."""
    page_mode, allowed_types = PAGE_MODES[page]
    period = _selected_period(request)
    ctx = manual_context(request, page_mode=page_mode,
                         allowed_revenue_types=allowed_types)
    return {
        **ctx,
        'manual_page_key': page,
        'manual_allowed_types': ','.join(allowed_types),
        'manual_period': period,
        'manual_period_closed': bool(period and period.is_closed),
        'void_reasons': mr.VOID_REASONS,
        'adjustment_reasons': mr.ADJUSTMENT_REASONS,
    }


def _selected_period(request):
    """The period the page currently reports (first selected year/month)."""
    rctx = RevenueContext(request)
    return rctx.period
