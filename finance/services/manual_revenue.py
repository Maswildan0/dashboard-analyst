"""Manual revenue: create / edit / void / restore / adjust + audit trail.

Every manual mutation writes BOTH its own row (`ManualRevenueEntry`) and an
immutable audit event (`FinancialDataAuditLog`, model 'ManualRevenueEntry').
The audit row is append-only: nothing here updates or deletes it, which is
what keeps the DELETE event readable after a later RESTORE.

Enforced HERE (never only in a template, never only in JS):

  OPEN-period lock    create / edit / void / restore require an OPEN period;
                      a CLOSED period raises ManualRevenueError (HTTP 400).
  1 project = 1 PP    the PP and revenue account must follow the project's
  = 1 account         mapped GL; a mismatch is rejected with the
                      operator-facing message.
  No physical delete  Hapus is a VOID status change on the same row.
  Decimal only        amounts parse via Decimal; NaN/Inf/garbage rejected and
                      nothing is rounded beyond the model's 2dp precision.
  Provenance          MANUAL = operator's own recognition (editable/voidable),
                      ADJUSTMENT = correction of an imported row that is
                      referenced but NEVER overwritten.
  Imported is locked  a row whose source is SIMKUG GL / NTF import has no
                      edit or delete path at all — only an Adjustment.

The aggregation helpers (`posted_entries`, `total_for_projects`, `posting_rows`,
`entries_for_scope`) are the ONE place POSTED manual rows enter actual revenue,
so Data Revenue, Data TF, Data NTF Research, Data NTF Project, the Revenue
Overview and the Financial Performance Overview all read identical numbers.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date as _parse_date

from finance.models import (
    FinancialDataAuditLog,
    GLProjectMapping,
    ManualRevenueEntry,
    OrganizationUnit,
    PPMaster,
    Project,
    RevenueAccount,
    RevenueCategory,
    RevenueLedger,
)

ZERO = Decimal('0')
CENTS = Decimal('0.01')

# Reason options the void / adjustment dialogs offer; 'Lainnya' requires text.
VOID_REASONS = [
    'Salah input nominal',
    'Double entry',
    'Salah PP',
    'Salah akun',
    'Pembatalan transaksi',
    'Lainnya',
]
ADJUSTMENT_REASONS = [
    'Koreksi nilai kontrak',
    'Koreksi pengakuan',
    'Penyesuaian audit',
    'Lainnya',
]

# Match statuses that make a GL row authoritative for a project (mirrors
# revenue_project_service._MATCH_OK — a mapping must be trusted to bind PP).
_MATCH_OK = ['AUTO_MATCHED', 'VERIFIED', 'NEEDS_REVIEW']

CLOSED_MESSAGE = (
    'Periode {period} sudah ditutup. Data pada periode CLOSED tidak dapat '
    'diubah secara langsung; gunakan Adjustment pada periode OPEN.'
)
RESTORE_CLOSED_MESSAGE = (
    'Data berada pada periode yang sudah ditutup dan tidak dapat dipulihkan '
    'secara langsung. Koreksi harus melalui Adjustment di periode OPEN.'
)
MISMATCH_MESSAGE = 'Project ini terdaftar pada PP/Akun Pendapatan yang berbeda.'
IMPORTED_MESSAGE = (
    'Data ini berasal dari sumber import (SIMKUG/NTF) dan tidak dapat diubah '
    'langsung. Gunakan Koreksi / Adjustment.'
)


class ManualRevenueError(Exception):
    """Domain rejection; `status` drives the HTTP code the view returns."""

    def __init__(self, message, *, field=None, status=400):
        super().__init__(message)
        self.message = message
        self.field = field
        self.status = status


# ---------------------------------------------------------------------------
# Input parsing (§36) — Decimal, never float, never NaN/Infinity
# ---------------------------------------------------------------------------
def _unformat(text):
    """Indonesian input -> plain decimal string, else unchanged.

    Accepts both the grouped-with-decimals form ('1.234.567,89') and the
    grouped-integer form ('1.234.567'), which is what operators paste from a
    spreadsheet or a report. A single dot followed by 1-2 digits is still read
    as a decimal point ('1234.56'), never as a thousands separator.
    """
    head, sep, tail = text.partition(',')
    if sep:
        # '1.234.567,89' -> grouped head with a decimal comma.
        bare = head.lstrip('-')
        if bare and len(bare) > 3 and all(p.isdigit() for p in bare.split('.')):
            return f'{head.replace(".", "")}.{tail}'
        return f'{head}.{tail}'
    bare = text.lstrip('-')
    parts = bare.split('.')
    # Two or more dot groups ('1.234.567') are unambiguously thousands
    # separators. A SINGLE dot is left alone and read as a decimal point:
    # '1.005' could mean either 1005 (grouped) or 1.005 (unrepresentable at
    # 2dp), and guessing wrong would move the amount by three orders of
    # magnitude — so it is rejected instead (see the 2dp check).
    if len(parts) > 2 and all(p.isdigit() for p in parts) \
            and all(len(p) == 3 for p in parts[1:]):
        return text.replace('.', '')
    return text


def parse_amount(raw, *, field='amount', label='Nominal Pengakuan',
                 required=True, allow_negative=True):
    """Signed Decimal from user input. Rejects NaN/Infinity/invalid strings."""
    if raw is None or str(raw).strip() == '':
        if required:
            raise ManualRevenueError(f'{label} wajib diisi.', field=field)
        return None
    text = _unformat(str(raw).strip().replace(' ', ''))
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError, TypeError):
        raise ManualRevenueError(f'{label} tidak valid.', field=field)
    if not value.is_finite():
        raise ManualRevenueError(f'{label} tidak valid.', field=field)
    if value == ZERO:
        raise ManualRevenueError(f'{label} tidak boleh 0.', field=field)
    if not allow_negative and value < ZERO:
        raise ManualRevenueError(f'{label} tidak boleh negatif.', field=field)
    if value != value.quantize(CENTS):
        raise ManualRevenueError(
            f'{label} maksimal 2 angka desimal.', field=field)
    return value


def parse_project_value(raw):
    """Nilai Proyek is project-master data, never derived from GL (§9)."""
    return parse_amount(raw, field='project_value', label='Nilai Proyek',
                        required=False, allow_negative=False)


def parse_date(raw, *, field='transaction_date', label='Tanggal Pengakuan',
               required=True):
    if raw is None or str(raw).strip() == '':
        if required:
            raise ManualRevenueError(f'{label} wajib diisi.', field=field)
        return None
    value = _parse_date(str(raw).strip())
    if value is None:
        raise ManualRevenueError(f'{label} tidak valid.', field=field)
    return value


def parse_choice(raw, choices, *, field, label, required=True):
    value = (str(raw).strip() if raw is not None else '')
    if not value:
        if required:
            raise ManualRevenueError(f'{label} wajib diisi.', field=field)
        return ''
    for allowed in choices:
        if value.lower() == allowed.lower():
            return allowed
    raise ManualRevenueError(f'{label} tidak valid.', field=field)


# ---------------------------------------------------------------------------
# Master-data resolution (business codes, never raw client-supplied ids)
# ---------------------------------------------------------------------------
def resolve_master(*, category_code=None, organization_id=None, pp_code=None,
                   account_code=None, project_id=None):
    """Resolve the master rows a manual entry points at, or raise."""
    code = (str(category_code).strip().upper() if category_code else '')
    category = (RevenueCategory.objects.filter(code=code, is_active=True).first()
                if code else None)
    if category is None:
        raise ManualRevenueError('Jenis Revenue tidak valid.', field='revenue_type')

    organization = (OrganizationUnit.objects.filter(
        pk=organization_id, is_active=True).first() if organization_id else None)
    if organization is None:
        raise ManualRevenueError('Organization tidak valid.', field='organization')

    pp = (PPMaster.objects.filter(pp_code=str(pp_code).strip(), is_active=True).first()
          if pp_code else None)
    if pp is None:
        raise ManualRevenueError('Kode PP tidak valid.', field='pp')
    if pp.organization_unit_id and pp.organization_unit_id != organization.pk:
        raise ManualRevenueError(
            'Kode PP tidak terdaftar pada Organization yang dipilih.', field='pp')

    account = (RevenueAccount.objects.filter(
        account_code=str(account_code).strip(), is_active=True).first()
        if account_code else None)
    if account is None:
        raise ManualRevenueError('Revenue Account tidak valid.', field='revenue_account')
    if account.revenue_category_id != category.pk:
        raise ManualRevenueError(
            'Revenue Account tidak termasuk Jenis Revenue yang dipilih.',
            field='revenue_account')

    project = (Project.objects.filter(pk=project_id, is_active=True).first()
               if project_id else None)
    if project_id and project is None:
        raise ManualRevenueError('Project tidak valid.', field='project')

    return {'category': category, 'organization': organization, 'pp': pp,
            'account': account, 'project': project}


def project_account_for(project):
    """The single revenue account of a project's mapped GL, or None when the
    project has no mapped account yet (a brand-new MANUAL object)."""
    if project is None:
        return None
    code = (GLProjectMapping.objects
            .filter(project=project, match_status__in=_MATCH_OK,
                    ledger__revenue_account__isnull=False)
            .values_list('ledger__revenue_account__account_code', flat=True)
            .first())
    if not code:
        return None
    return RevenueAccount.objects.filter(account_code=code).first()


def assert_project_consistency(project, pp, account):
    """1 project = 1 PP = 1 revenue account (§7).

    A project that already carries mapped GL must be keyed on exactly that
    PP and account; anything else is a different registration and is rejected.
    """
    if project is None:
        return
    if project.pp_id and project.pp_id != pp.pk:
        raise ManualRevenueError(MISMATCH_MESSAGE, field='pp')
    mapped_pp = (GLProjectMapping.objects
                 .filter(project=project, match_status__in=_MATCH_OK,
                         ledger__pp__isnull=False)
                 .values_list('ledger__pp__pp_code', flat=True)
                 .first())
    if mapped_pp and mapped_pp != pp.pp_code:
        raise ManualRevenueError(MISMATCH_MESSAGE, field='pp')
    mapped_account = project_account_for(project)
    if mapped_account is not None and mapped_account.pk != account.pk:
        raise ManualRevenueError(MISMATCH_MESSAGE, field='revenue_account')


def resolve_reference_ledger(ledger_id, *, account=None):
    """The imported GL row an adjustment corrects (read-only, §27-#28)."""
    if not ledger_id:
        return None
    ledger = (RevenueLedger.objects
              .filter(pk=ledger_id, revenue_account__isnull=False)
              .select_related('revenue_account').first())
    if ledger is None:
        raise ManualRevenueError('Transaksi sumber tidak ditemukan.', field='reference')
    if account is not None and ledger.revenue_account_id != account.pk:
        raise ManualRevenueError(
            'Transaksi sumber berada pada Revenue Account yang berbeda.',
            field='reference')
    return ledger


# ---------------------------------------------------------------------------
# Period lock (§25) — server side, for every mutation
# ---------------------------------------------------------------------------
def require_open(period):
    if period is None:
        raise ManualRevenueError('Periode tidak valid.', field='period')
    if period.is_closed:
        raise ManualRevenueError(
            CLOSED_MESSAGE.format(period=period), field='period', status=400)
    return period


def assert_own_row(entry):
    """Only operator-owned rows (MANUAL / ADJUSTMENT) are mutable."""
    if entry.source_type not in ('MANUAL', 'ADJUSTMENT'):
        raise ManualRevenueError(IMPORTED_MESSAGE, field='source_type')


def assert_editable(entry):
    """Edit requires an operator-owned, currently POSTED row (§17-#19)."""
    assert_own_row(entry)
    if entry.status != 'POSTED':
        raise ManualRevenueError(
            'Data sudah dihapus (VOID). Pulihkan terlebih dahulu untuk mengubahnya.',
            field='status')


# ---------------------------------------------------------------------------
# Audit trail (§29-#31, §60) — append-only, JSONB-safe
# ---------------------------------------------------------------------------
def json_safe(value):
    """Decimal/date/list/dict -> JSON-serialisable primitives.

    Money is normalised to the model's 2dp precision so two snapshots of the
    same amount always compare equal as strings (the audit timeline diffs them
    literally, and Decimal('100') vs Decimal('100.00') must not look like a
    change).
    """
    if isinstance(value, Decimal):
        return str(value.quantize(CENTS))
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    return value


def snapshot(entry):
    """Full auditable state of one entry (before_value / after_value)."""
    if entry is None:
        return None
    return json_safe({
        'id': entry.pk,
        'period': str(entry.period),
        'period_closed': entry.period.is_closed,
        'source_type': entry.source_type,
        'status': entry.status,
        'jenis_revenue': entry.revenue_category.code,
        'organization': entry.organization_unit.name,
        'pp': entry.pp.pp_code,
        'account': entry.revenue_account.account_code,
        'account_name': entry.revenue_account.account_name,
        'project_id': entry.project_id,
        'project_number': entry.project.project_number,
        'project_name': entry.project.project_name,
        'nilai_proyek': entry.project.project_value,
        'transaction_date': entry.transaction_date,
        'evidence_number': entry.evidence_number,
        'document_number': entry.document_number,
        'description': entry.description,
        'amount': entry.amount,
        'reason': entry.reason,
        'void_reason': entry.void_reason,
    })


def log_audit(action, entry, *, user=None, before=None, after=None, reason='',
              record_id=None):
    """Append one immutable audit event. There is no update/delete path."""
    actor = user if (user is not None and getattr(user, 'pk', None)) else None
    return FinancialDataAuditLog.objects.create(
        user=actor,
        action=action,
        model='ManualRevenueEntry',
        record_id=entry.pk if entry is not None else record_id,
        old_value=json_safe(before),
        new_value=json_safe(after),
        reason=reason or '',
    )


# Project-master events use their own model tag so they can never be confused
# with an entry event whose id happens to collide (§29).
PROJECT_AUDIT_MODEL = 'ManualProject'


def log_project_audit(action, project, *, user=None, before=None, after=None,
                      reason=''):
    """Append one immutable project-master audit event."""
    actor = user if (user is not None and getattr(user, 'pk', None)) else None
    return FinancialDataAuditLog.objects.create(
        user=actor,
        action=action,
        model=PROJECT_AUDIT_MODEL,
        record_id=project.pk if project is not None else None,
        old_value=json_safe(before),
        new_value=json_safe(after),
        reason=reason or '',
    )


def audit_events(entry):
    """Chronological audit timeline of one entry (oldest first)."""
    return list(FinancialDataAuditLog.objects
                .filter(model='ManualRevenueEntry', record_id=entry.pk)
                .select_related('user')
                .order_by('timestamp', 'id'))


def audit_events_for_project(project_id):
    """Timeline of a project: every entry's events + its master changes.

    Fetching by the project's entry ids (rather than by the project id) keeps
    entry events and project-master events in one chronological list without
    an id space collision.
    """
    entry_ids = list(ManualRevenueEntry.objects
                     .filter(project_id=project_id).values_list('pk', flat=True))
    return list(FinancialDataAuditLog.objects
                .filter(Q(model='ManualRevenueEntry', record_id__in=entry_ids)
                        | Q(model=PROJECT_AUDIT_MODEL, record_id=project_id))
                .select_related('user')
                .order_by('timestamp', 'id'))


# Audit fields rendered as amounts (a change shows 'Rp500 jt -> Rp550 jt').
AUDIT_MONEY_FIELDS = {'amount', 'nilai_proyek'}
AUDIT_LABELS = {
    'amount': 'Nominal Pengakuan',
    'nilai_proyek': 'Nilai Proyek',
    'transaction_date': 'Tanggal Pengakuan',
    'evidence_number': 'No Bukti',
    'document_number': 'No Dokumen',
    'description': 'Keterangan',
    'project_name': 'Nama Proyek',
    'project_number': 'No Proyek',
    'status': 'Status',
    'void_reason': 'Alasan Penghapusan',
    'reason': 'Alasan Koreksi',
    'pp': 'Kode PP',
    'account': 'Revenue Account',
    'jenis_revenue': 'Jenis Revenue',
    'organization': 'Organization',
}
# Fields shown in the timeline: the ones an operator can actually change.
AUDIT_TRACKED = [
    'amount', 'nilai_proyek', 'transaction_date', 'evidence_number',
    'document_number', 'description', 'status', 'void_reason', 'reason',
    'pp', 'account', 'project_number', 'project_name',
]


def audit_diff(before, after):
    """[(label, before, after, is_money)] for the fields that changed."""
    if not before:
        return []
    after = after or {}
    out = []
    for name in AUDIT_TRACKED:
        old, new = before.get(name), after.get(name)
        if old == new:
            continue
        if old in (None, '') and new in (None, ''):
            continue
        out.append((AUDIT_LABELS.get(name, name), old, new,
                    name in AUDIT_MONEY_FIELDS))
    return out


# ---------------------------------------------------------------------------
# Project master (manual provenance, §14)
# ---------------------------------------------------------------------------
def _next_manual_project_number(pp, account):
    """Deterministic, obviously-manual project number (prefix M-)."""
    prefix = f'M-{account.account_code}-{pp.pp_code}-'
    last = (Project.objects.filter(project_number__startswith=prefix)
            .order_by('-project_number').values_list('project_number', flat=True).first())
    seq = int(last[len(prefix):]) + 1 if last and last[len(prefix):].isdigit() else 1
    return f'{prefix}{seq:02d}'


def create_manual_project(*, pp, account, organization, period, project_name='',
                          project_number='', project_value=None, user=None):
    """Register a MANUAL project/object so it is distinguishable from import."""
    name = (project_name or '').strip()
    number = (project_number or '').strip()
    if not name and not number:
        raise ManualRevenueError(
            'Nama Proyek / Objek atau No Proyek wajib diisi.', field='project_name')
    number = number or _next_manual_project_number(pp, account)
    if Project.objects.filter(project_number=number).exists():
        raise ManualRevenueError('No Proyek sudah terdaftar.', field='project_number')
    organization = organization or pp.organization_unit
    project = Project.objects.create(
        project_number=number,
        project_name=name,
        pp=pp,
        organization_unit=organization,
        campus=organization.campus if organization else None,
        project_value=project_value or ZERO,
        first_seen_period=period,
        last_seen_period=period,
        source_status='MANUAL',
        source_type='MANUAL',
        is_active=True,
    )
    log_project_audit('CREATE', project, user=user, after={
        'object_type': 'Project',
        'project_number': project.project_number,
        'project_name': project.project_name,
        'pp': pp.pp_code,
        'account': account.account_code,
        'jenis_revenue': account.revenue_category.code,
        'organization': organization.name if organization else '',
        'nilai_proyek': str(project.project_value),
        'source_type': 'MANUAL',
    }, reason='Pembuatan project/objek manual')
    return project


@transaction.atomic
def update_manual_project(project, *, project_name=None, project_number=None,
                          project_value=None, user=None):
    """Project-level edit: name / number / value of a MANUAL project only.

    Deliberately separate from `update_entry` (§18): this path never changes a
    recognition amount, and an imported project's master metadata stays
    read-only so a correction there must go through an Adjustment.
    """
    project = Project.objects.select_for_update().get(pk=project.pk)
    if project.source_type != 'MANUAL':
        raise ManualRevenueError(
            'Project ini berasal dari data import sehingga data master proyek '
            'tidak dapat diubah langsung.', field='project_number')
    before = json_safe({
        'object_type': 'Project',
        'project_number': project.project_number,
        'project_name': project.project_name,
        'nilai_proyek': project.project_value,
        'pp': project.pp.pp_code if project.pp else '',
        'source_type': project.source_type,
    })
    changed = _apply_project_master(
        project,
        project_name=(project_name or '').strip() or None,
        project_number=(project_number or '').strip() or None,
        project_value=project_value,
    )
    if not changed:
        return project
    log_project_audit('UPDATE', project, user=user, before=before, after=json_safe({
        'object_type': 'Project',
        'project_number': project.project_number,
        'project_name': project.project_name,
        'nilai_proyek': project.project_value,
        'pp': project.pp.pp_code if project.pp else '',
        'source_type': project.source_type,
    }), reason='Perubahan master project manual')
    return project


def _apply_project_master(project, *, project_name=None, project_number=None,
                          project_value=None, organization=None):
    """Update MANUAL project metadata; imported project masters are read-only."""
    if project is None or project.source_type != 'MANUAL':
        return False
    fields = []
    if project_name and project_name != project.project_name:
        project.project_name = project_name
        fields.append('project_name')
    if project_number and project_number != project.project_number:
        if Project.objects.filter(project_number=project_number).exclude(pk=project.pk).exists():
            raise ManualRevenueError('No Proyek sudah terdaftar.', field='project_number')
        project.project_number = project_number
        fields.append('project_number')
    if project_value is not None and project_value != project.project_value:
        project.project_value = project_value
        fields.append('project_value')
    if organization is not None and project.organization_unit_id != organization.pk:
        project.organization_unit = organization
        project.campus = organization.campus
        fields += ['organization_unit', 'campus']
    if fields:
        project.save(update_fields=fields + ['updated_at'])
        return True
    return False


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------
@transaction.atomic
def create_entry(*, period, category, organization, pp, account, project=None,
                 transaction_date, amount, evidence_number='', document_number='',
                 description='', source_type='MANUAL', reference_ledger=None,
                 reason='', user=None, project_name='', project_number='',
                 project_value=None):
    """Create one POSTED recognition, optionally with a new MANUAL project.

    Mode A (project is None) registers the project/object first; mode B keys a
    recognition onto an existing project. Needing a termin never duplicates a
    project (§8).
    """
    require_open(period)
    if source_type not in ('MANUAL', 'ADJUSTMENT'):
        raise ManualRevenueError('Source type tidak valid.', field='source_type')
    if reference_ledger is not None and source_type != 'ADJUSTMENT':
        raise ManualRevenueError(
            'Referensi sumber hanya berlaku untuk Adjustment.', field='reference')
    if source_type == 'ADJUSTMENT' and not (reason or '').strip():
        raise ManualRevenueError('Alasan koreksi wajib diisi.', field='reason')

    if source_type == 'MANUAL':
        project_name = (project_name or '').strip()
        project_number = (project_number or '').strip()
    else:
        # An adjustment corrects an EXISTING imported object; it may never
        # invent one, or the correction would create a parallel project instead
        # of moving the actual revenue of the object it claims to correct.
        if project is None:
            raise ManualRevenueError(
                'Koreksi harus ditujukan pada project/objek yang sudah ada.',
                field='project')
        project_name = project_number = ''

    if project is None:
        project = create_manual_project(
            pp=pp, account=account, organization=organization, period=period,
            project_name=project_name, project_number=project_number,
            project_value=project_value, user=user)
    else:
        assert_project_consistency(project, pp, account)
        if project.source_type == 'MANUAL':
            _apply_project_master(project, project_name=project_name or None,
                                  project_number=project_number or None,
                                  project_value=project_value,
                                  organization=organization)
        elif project_name or project_number:
            raise ManualRevenueError(
                'Project ini berasal dari data import sehingga nama/nomor '
                'proyek tidak dapat diubah langsung.', field='project_name')

    actor = user if (user is not None and getattr(user, 'pk', None)) else None
    entry = ManualRevenueEntry.objects.create(
        period=period,
        revenue_category=category,
        organization_unit=organization,
        pp=pp,
        revenue_account=account,
        project=project,
        source_type=source_type,
        status='POSTED',
        transaction_date=transaction_date,
        evidence_number=(evidence_number or '').strip(),
        document_number=(document_number or '').strip(),
        description=(description or '').strip(),
        amount=amount,
        reference_ledger=reference_ledger,
        reason=(reason or '').strip(),
        created_by=actor,
        updated_by=actor,
    )
    log_audit('ADJUSTMENT' if source_type == 'ADJUSTMENT' else 'CREATE',
              entry, user=user, after=snapshot(entry), reason=entry.reason)
    return entry


@transaction.atomic
def update_entry(entry, *, amount=None, transaction_date=None, evidence_number=None,
                 document_number=None, description=None, user=None,
                 project_name=None, project_number=None, project_value=None):
    """Edit transaction-level fields (plus MANUAL project master metadata)."""
    entry = _locked(entry)
    assert_editable(entry)
    require_open(entry.period)

    before = snapshot(entry)
    if amount is not None:
        entry.amount = amount
    if transaction_date is not None:
        entry.transaction_date = transaction_date
    if evidence_number is not None:
        entry.evidence_number = evidence_number.strip()
    if document_number is not None:
        entry.document_number = document_number.strip()
    if description is not None:
        entry.description = description.strip()
    entry.updated_by = user if (user is not None and getattr(user, 'pk', None)) else None
    entry.save()

    if entry.project.source_type == 'MANUAL':
        _apply_project_master(
            entry.project,
            project_name=(project_name or '').strip() or None,
            project_number=(project_number or '').strip() or None,
            project_value=project_value,
        )
    elif (project_name or '').strip() or (project_number or '').strip():
        raise ManualRevenueError(
            'Project ini berasal dari data import sehingga nama/nomor proyek '
            'tidak dapat diubah langsung.', field='project_name')

    log_audit('UPDATE', entry, user=user, before=before, after=snapshot(entry))
    return entry


@transaction.atomic
def void_entry(entry, *, reason, user=None):
    """Soft delete: status -> VOID with reason, actor and timestamp."""
    entry = _locked(entry)
    assert_own_row(entry)
    if entry.status == 'VOID':
        raise ManualRevenueError('Data sudah dihapus sebelumnya.', field='status')
    require_open(entry.period)
    if not (reason or '').strip():
        raise ManualRevenueError('Alasan penghapusan wajib diisi.', field='void_reason')

    before = snapshot(entry)
    actor = user if (user is not None and getattr(user, 'pk', None)) else None
    entry.status = 'VOID'
    entry.void_reason = reason.strip()
    entry.voided_at = timezone.now()
    entry.voided_by = actor
    entry.updated_by = actor
    entry.save(update_fields=['status', 'void_reason', 'voided_at', 'voided_by',
                              'updated_by', 'updated_at'])
    # Append-only: this DELETE event survives every later RESTORE.
    log_audit('DELETE', entry, user=user, before=before, after=snapshot(entry),
              reason=entry.void_reason)
    return entry


@transaction.atomic
def restore_entry(entry, *, user=None):
    """VOID -> POSTED while the target period is still OPEN (§23, §24)."""
    entry = _locked(entry)
    assert_own_row(entry)
    if entry.status != 'VOID':
        raise ManualRevenueError('Hanya data yang dihapus dapat dipulihkan.',
                                 field='status')
    if entry.period.is_closed:
        raise ManualRevenueError(RESTORE_CLOSED_MESSAGE, field='period', status=400)

    before = snapshot(entry)
    actor = user if (user is not None and getattr(user, 'pk', None)) else None
    entry.status = 'POSTED'
    entry.restored_at = timezone.now()
    entry.restored_by = actor
    entry.updated_by = actor
    entry.save(update_fields=['status', 'restored_at', 'restored_by',
                              'updated_by', 'updated_at'])
    log_audit('RESTORE', entry, user=user, before=before, after=snapshot(entry))
    return entry


def _locked(entry):
    return (ManualRevenueEntry.objects.select_for_update().select_related(
        'period', 'project', 'pp', 'revenue_account', 'revenue_category',
        'organization_unit').get(pk=entry.pk))


# ---------------------------------------------------------------------------
# Canonical aggregation — the single place POSTED manual rows join actual
# revenue. Every reader calls these, so a manual amount can never be counted
# twice (Data Revenue + Revenue Overview read the same rows) nor missed.
# ---------------------------------------------------------------------------
def posted_entries():
    """All POSTED rows; VOID (and a future DRAFT) never feed actual revenue."""
    return ManualRevenueEntry.objects.filter(status='POSTED')


def _scope(qs, *, periods=None, year=None, month=None, month_lte=None, date_lte=None):
    if periods is not None:
        qs = qs.filter(period__in=list(periods))
    if year is not None:
        qs = qs.filter(period__year=year)
        if month is not None:
            qs = qs.filter(period__month=month)
        elif month_lte is not None:
            qs = qs.filter(period__month__lte=month_lte)
    if date_lte is not None:
        qs = qs.filter(transaction_date__lte=date_lte)
    return qs


def total_for_projects(project_ids, *, periods=None, year=None, month=None,
                       month_lte=None, date_lte=None, account=None,
                       category=None):
    """{project_id: Decimal} POSTED totals in the same scope as mapped GL."""
    ids = list(project_ids)
    if not ids:
        return {}
    qs = posted_entries().filter(project_id__in=ids)
    if account is not None:
        qs = qs.filter(revenue_account=account)
    elif category is not None:
        qs = qs.filter(revenue_account__revenue_category=category)
    qs = _scope(qs, periods=periods, year=year, month=month, month_lte=month_lte,
                date_lte=date_lte)
    out = {}
    for row in qs.values('project_id').annotate(total=Sum('amount')):
        out[row['project_id']] = row['total'] or ZERO
    return out


def posting_rows(project_ids):
    """[(project_id, account_code, account_id, transaction_date, amount)].

    Every POSTED manual recognition of `project_ids`. The row builders merge
    these into their per-project-per-account buckets, so a manual recognition
    is dated, filtered and totalled EXACTLY like a mapped GL line and the
    periodic buckets need no special case.
    """
    ids = list(project_ids)
    if not ids:
        return []
    return list(
        posted_entries()
        .filter(project_id__in=ids, revenue_account__isnull=False)
        .values_list('project_id', 'revenue_account__account_code',
                     'revenue_account_id', 'transaction_date', 'amount')
    )


def entries_for_scope(*, project=None, account=None, category=None, pp=None,
                      periods=None, year=None, month=None, month_lte=None,
                      date_lte=None):
    """POSTED entries for one scope, newest first (history / drill-down)."""
    qs = posted_entries().select_related(
        'period', 'revenue_account', 'pp', 'pp__organization_unit', 'project')
    if project is not None:
        qs = qs.filter(project=project)
    if account is not None:
        qs = qs.filter(revenue_account=account)
    elif category is not None:
        qs = qs.filter(revenue_account__revenue_category=category)
    if pp is not None:
        qs = qs.filter(pp=pp)
    qs = _scope(qs, periods=periods, year=year, month=month, month_lte=month_lte,
                date_lte=date_lte)
    return qs.order_by('-transaction_date', '-id')


def deleted_entries(*, category_codes=None):
    """VOID rows for the Data Terhapus panel (§22), newest void first."""
    qs = (ManualRevenueEntry.objects
          .filter(status='VOID')
          .select_related('period', 'revenue_category', 'organization_unit',
                          'pp', 'revenue_account', 'project', 'voided_by'))
    if category_codes:
        qs = qs.filter(revenue_category__code__in=list(category_codes))
    return qs.order_by('-voided_at', '-id')


def editable_ledger_rows(*, account_code=None, pp_code=None, project_id=None):
    """Imported GL rows an Adjustment may reference (source stays untouched).

    Returns an UNSLICED queryset so callers can narrow it further before the
    limit is applied at the end of the option endpoint.
    """
    qs = (RevenueLedger.objects
          .filter(revenue_account__isnull=False)
          .select_related('period', 'revenue_account', 'pp', 'pp__organization_unit')
          .order_by('-posting_date', '-id'))
    if account_code:
        qs = qs.filter(revenue_account__account_code=account_code)
    if pp_code:
        qs = qs.filter(pp__pp_code=pp_code)
    if project_id:
        qs = qs.filter(project_mappings__project_id=project_id)
    return qs
