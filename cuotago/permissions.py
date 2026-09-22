from functools import wraps

from flask import abort
from flask_login import current_user

ROLE_LABELS = {
    "owner": "Propietario",
    "admin": "Administrador",
    "collector": "Cobrador",
    "sales": "Vendedor",
    "staff": "Usuario",
    "viewer": "Consulta",
    "superadmin": "Superadmin",
}

ROLE_PERMISSIONS = {
    "owner": {"*"},
    "admin": {
        "clients.view", "clients.manage", "contracts.view", "contracts.create", "contracts.manage",
        "collections.view", "collections.collect", "inventory.view", "inventory.manage", "purchases.view", "purchases.manage",
        "reports.view", "expenses.view", "expenses.manage", "audit.view", "backup.export", "settings.manage", "team.manage",
    },
    "collector": {
        "clients.view", "clients.manage", "contracts.view", "collections.view", "collections.collect",
        "reports.view", "inventory.view",
    },
    "sales": {
        "clients.view", "clients.manage", "contracts.view", "contracts.create", "inventory.view", "purchases.view",
        "collections.view",
    },
    "staff": {
        "clients.view", "clients.manage", "contracts.view", "contracts.create", "collections.view", "collections.collect",
        "inventory.view", "purchases.view", "reports.view",
    },
    "viewer": {"clients.view", "contracts.view", "collections.view", "inventory.view", "purchases.view", "reports.view"},
    "superadmin": {"*"},
}


def has_permission(user, permission):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    permissions = ROLE_PERMISSIONS.get(getattr(user, "role", ""), set())
    return "*" in permissions or permission in permissions


def permission_required(permission):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not has_permission(current_user, permission):
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator
