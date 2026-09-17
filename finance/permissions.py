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

Bootstrap fallback (§4)
-----------------------
Until an administrator assigns ANY of the six permissions above, the capability
set would be all-false and every gated control would vanish — only the ungated
"Data Terhapus" button would render and the feature would look broken. While
that is true, a SIGNED-IN operator is granted the capabilities anyway, so the
CRUD stays usable before roles are finalised.

The fallback is self-disabling: the moment one of the six permissions is granted
to any user or group, `in_bootstrap()` turns False and the strict path returns
for everyone. It is also gated on `REVENUE_PERMISSION_FALLBACK` so the strict
path can be exercised locally. Authentication is NEVER part of the fallback: an
anonymous request is rejected here no matter what, and the period lock / master
validation in finance.services.manual_revenue still apply to every write.
"""
from functools import wraps

from django.conf import settings
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


def fallback_enabled():
    """Whether the not-yet-assigned fallback may apply at all."""
    return str(getattr(settings, 'REVENUE_PERMISSION_FALLBACK', True)).lower() not in (
        '0', 'false', 'no', 'off')


def operator_permissions_assigned():
    """True once ONE manual permission is granted to any user or group.

    That single probe is what makes the fallback temporary: assigning the
    Revenue Operator group (manage.py seed_revenue_operator) switches the
    feature to the strict path without any further configuration.
    """
    from django.contrib.auth.models import Permission
    codenames = {label.split('.', 1)[1] for label in ACTION_PERMS.values()}
    granted = Permission.objects.filter(
        content_type__app_label='finance', codename__in=codenames)
    return granted.filter(user__isnull=False).exists() \
        or granted.filter(group__isnull=False).exists()


def in_bootstrap():
    """True while no operator permission has been assigned anywhere (§4).

    Only meaningful for an authenticated caller — see `allowed()`; the period
    lock and master validation are enforced server-side regardless.
    """
    return fallback_enabled() and not operator_permissions_assigned()


def _is_operator(user):
    return bool(user and user.is_authenticated and user.is_active)


def allowed(user, action):
    """True when `user` may perform `action`.

    A signed-in operator with the matching permission always passes (a
    superuser holds every permission). While nothing has been assigned yet an
    authenticated operator passes too — see the module docstring.
    """
    perm = ACTION_PERMS.get(action)
    if perm is None or not _is_operator(user):
        return False
    return bool(user.has_perm(perm)) or in_bootstrap()


def capabilities(user):
    """{action: bool} for template rendering (never the enforcement point).

    Anonymous visitors get an all-false set, which is why the templates omit
    every gated control instead of rendering a button that would only 403.
    """
    if not _is_operator(user):
        return {action: False for action in ACTION_PERMS}
    bootstrap = in_bootstrap()
    return {action: (bootstrap or user.has_perm(perm))
            for action, perm in ACTION_PERMS.items()}


def require(user, action):
    """Raise PermissionDenied unless `user` may perform `action`.

    Authentication is checked FIRST and is never relaxed: anonymous requests
    are rejected here rather than redirected, so a write attempt without a
    session fails loudly (HTTP 403) instead of silently rendering a login page
    the API caller cannot use.
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
