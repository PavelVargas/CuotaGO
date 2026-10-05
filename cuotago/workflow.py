"""A small, whitelisted navigation context; never accepts redirect URLs."""
from flask import g, request, url_for
from flask_login import current_user
from .models import Asset, Client
from .permissions import has_permission


def origin_context():
    if hasattr(g, '_dealer_origin'):
        return g._dealer_origin
    g._dealer_origin = None
    if not current_user.is_authenticated:
        return None
    kind = request.values.get('origin', '')
    identifier = request.values.get('origin_id', type=int)
    choices = {
        'asset': (Asset, 'inventory.view', 'main.asset_detail', 'asset_id', 'name', 'inventory'),
        'client': (Client, 'clients.view', 'main.client_detail', 'client_id', 'full_name', 'users'),
    }
    if kind not in choices or not identifier or identifier < 1:
        return None
    model, permission, endpoint, key, attr, icon = choices[kind]
    if not has_permission(current_user, permission):
        return None
    item = model.query.filter_by(id=identifier, organization_id=current_user.organization_id).first()
    if item is None:
        return None
    g._dealer_origin = {
        'kind': kind, 'id': item.id, 'label': getattr(item, attr), 'icon': icon,
        'url': url_for(endpoint, **{key: item.id}),
    }
    return g._dealer_origin


def contextual_url(endpoint, **values):
    context = origin_context()
    if context:
        values.update(origin=context['kind'], origin_id=context['id'])
    return url_for(endpoint, **values)


def safe_local_path(value):
    """Only an absolute path on this host, not a URL or browser-normalized host."""
    from urllib.parse import urlsplit, unquote
    if not isinstance(value, str) or not value.startswith('/'):
        return False
    decoded = unquote(value)
    if decoded.startswith('//') or '\\' in decoded or any(ord(c) < 32 for c in decoded):
        return False
    parsed = urlsplit(value)
    return not parsed.scheme and not parsed.netloc
