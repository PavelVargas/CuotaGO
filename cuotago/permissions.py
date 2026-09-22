"""Simple role-based permissions for CuotaGo.

Keep the UI calm: users choose a job role, not dozens of checkboxes.  Routes still
check explicit permissions so hiding a button is never the security boundary.
"""
from functools import wraps

from flask import abort
from flask_login import current_user


ROLE_LABELS = {
    "owner": "Propietario",
    "admin": "Administrador",  # legacy alias kept for existing databases
    "manager": "Supervisor",
    "collector": "Cobrador",
    "seller": "Vendedor",
    "sales": "Vendedor",  # v1.16 legacy alias
    "staff": "Operador",
    "viewer": "Consulta",  # v1.16 legacy alias
    "superadmin": "Superadmin",
}

ASSIGNABLE_ROLES = ("owner", "manager", "collector", "seller", "staff", "viewer")

# Permissions are intentionally task-oriented.  This is easier to audit than
# checking role names throughout controllers.
ALL_PERMISSIONS = {
    "clients.view", "clients.manage",
    "inventory.view", "inventory.manage",
    "purchases.view", "purchases.manage",
    "contracts.view", "contracts.create", "contracts.modify", "contracts.cancel",
    "collections.view", "collections.manage", "payments.view", "payments.record",
    "expenses.view", "expenses.manage",
    "reports.view", "audit.view", "data.export", "team.manage",
}

ROLE_PERMISSIONS = {
    "owner": ALL_PERMISSIONS,
    "admin": ALL_PERMISSIONS,
    "manager": ALL_PERMISSIONS - {"team.manage"},
    "collector": {
        "clients.view", "contracts.view", "collections.view", "collections.manage",
        "payments.view", "payments.record",
    },
    "seller": {
        "clients.view", "clients.manage", "inventory.view",
        "contracts.view", "contracts.create", "payments.view",
    },
    "sales": {
        "clients.view", "clients.manage", "inventory.view",
        "contracts.view", "contracts.create", "payments.view",
    },
    "viewer": {
        "clients.view", "inventory.view", "purchases.view", "contracts.view",
        "collections.view", "payments.view", "reports.view",
    },
    "staff": {
        "clients.view", "clients.manage", "inventory.view", "contracts.view", "contracts.create",
        "collections.view", "collections.manage", "payments.view", "payments.record",
    },
    "superadmin": ALL_PERMISSIONS,
}

# Compatibility with v1.16 permission names.  New code uses the clearer
# task-oriented names above, while existing sessions/tests keep working.
PERMISSION_ALIASES = {
    "contracts.manage": "contracts.modify",
    "collections.collect": "payments.record",
    "backup.export": "data.export",
    "settings.manage": "team.manage",
}

MODULE_PERMISSIONS = {
    "agreements": "contracts.view",
    "collections": "collections.view",
    "notifications": "collections.view",
    "clients": "clients.view",
    "purchases": "purchases.view",
    "inventory": "inventory.view",
    "calendar": "collections.view",
    "reports": "reports.view",
    "expenses": "expenses.view",
    "documents": None,
    "settings": None,
}


def role_label(role):
    return ROLE_LABELS.get((role or "").strip().lower(), (role or "Usuario").capitalize())


def has_permission(user, permission):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    role = (getattr(user, "role", "") or "staff").strip().lower()
    permission = PERMISSION_ALIASES.get(permission, permission)
    return permission in ROLE_PERMISSIONS.get(role, set())


def permission_required(permission):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not has_permission(current_user, permission):
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def visible_modules(modules, user):
    visible = []
    for module in modules:
        required = MODULE_PERMISSIONS.get(module.get("slug"))
        if required is None or has_permission(user, required):
            visible.append(module)
    return visible
