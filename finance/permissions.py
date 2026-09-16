"""Server-side authorization for manual revenue writes (§19, §33, §34).

Every manual mutation goes through `require(user, ACTION)`. The check runs on
the SERVER for each request: hiding a button in the template is presentation
only and is never the enforcement point.

Authorization reuses Django's own permission machinery, so operators are
granted rights through groups / user permissions in the admin exactly like
every other Django app:

    finance.add_manualrevenueentry         -> can_create_manual_revenue
    finance.change_manualrevenueentry      -> can_edit_manual_revenue
    finance.delete_manualrevenueentry      -> can_void_manual_revenue
    finance.restore_entry (custom)         -> can_restore_manual_revenue
    finance.create_adjustment (custom)     -> can_create_adjustment
    finance.view_audit (custom)            -> can_view_audit_history

`ADJUSTMENT` requires the dedicated `create_adjustment` permission: correcting
an imported source is a stronger right than keying a new recognition.
`AUTHENTICATED_ONLY` actions need a session but no specific permission, which
is how the audit history stays readable for every signed-in analyst while
still being closed to anonymous visitors.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied

# Model-level permission codenames used by the manual revenue feature.
PERM_CREATE = 'finance.add_manualrevenueentry'
PERM_EDIT = 'finance.change_manualrevenueentry'
PERM_VOID = 'finance.delete_manualrevenueentry'
PERM_RESTORE = 'finance.restore_entry'
PERM_ADJUST = 'finance.create_adjustment'
PERM_VIEW_AUDIT = 'finance.view_audit'

# Human labels for the UI (button visibility / disabled tooltips).
ACTION_PERMS = {
    'create': PERM_CREATE,
    'edit': PERM_EDIT,
    'void': PERM_VOID,
    'restore': PERM_RESTORE,
    'adjustment': PERM_ADJUST,
    'view_audit': PERM_VIEW_AUDIT,
}


def allowed(user, action):
    """True when `user` may perform `action` (superusers always may)."""
    perm = ACTION_PERMS.get(action)
    if perm is None:
        return False
    return bool(user and user.is_authenticated and user.has_perm(perm))


def capabilities(user):
    """{action: bool} for template rendering (never the enforcement point)."""
    return {action: allowed(user, action) for action in ACTION_PERMS}


def require(user, action):
    """Raise PermissionDenied unless `user` may perform `action`.

    Anonymous requests are rejected here rather than redirected, so a write
    attempt without a session fails loudly (HTTP 403) instead of silently
    rendering a login page the API caller cannot use.
    """
    if not user or not user.is_authenticated:
        raise PermissionDenied('Autentikasi diperlukan untuk mengubah data revenue.')
    if not user.is_active:
        raise PermissionDenied('Akun tidak aktif.')
    if not allowed(user, action):
        raise PermissionDenied(
            f'Anda tidak memiliki izin untuk aksi ini ({ACTION_PERMS[action]}).')


def require_authenticated(user):
    """Read-only endpoints (history / deleted panel) need a session only."""
    if not user or not user.is_authenticated:
        raise PermissionDenied('Autentikasi diperlukan.')
    if not user.is_active:
        raise PermissionDenied('Akun tidak aktif.')


def permission_required(action):
    """Decorator for a view function performing one manual `action`."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            require(request.user, action)
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


def authenticated_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        require_authenticated(request.user)
        return view(request, *args, **kwargs)
    return wrapper
