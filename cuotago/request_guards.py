"""Application guards, explicit billing access and assigned-portfolio scoping."""
from datetime import timedelta
from flask import g, request, session, redirect, url_for, jsonify, current_app, has_request_context
from flask_login import current_user
from sqlalchemy import event, select
from sqlalchemy.orm import Session, with_loader_criteria
from .extensions import db
from .business_time import utcnow, business_date
from .secure_sessions import recent_auth
from .models import Client, Contract, Payment, Installment, PaymentPromise, CollectionNote
from .operations.models import OrganizationControls

# Runs on root ORM queries as well as SELECTs of individual columns. Relationship
# loads propagate the criteria from the root query; stock availability deliberately
# reads complete asset relationships, not just a collector's portfolio.
@event.listens_for(Session, 'do_orm_execute')
def assigned_portfolio(state):
    if not has_request_context() or not getattr(g, 'collector_scope', None):
        return
    if not state.is_select or state.is_relationship_load or state.is_column_load or state.execution_options.get('cuotago_full_stock'):
        return
    org_id, user_id = g.collector_scope
    # Core table columns prevent ORM criteria from recursively re-applying
    # themselves inside the very subqueries used to define the scope.
    client_cols, contract_cols = Client.__table__.c, Contract.__table__.c
    clients = select(client_cols.id).where(client_cols.organization_id == org_id, client_cols.assigned_collector_id == user_id)
    contracts = select(contract_cols.id).where(contract_cols.organization_id == org_id, contract_cols.client_id.in_(clients))
    state.statement = state.statement.options(
        with_loader_criteria(Client, (Client.organization_id == org_id) & (Client.assigned_collector_id == user_id), include_aliases=True),
        with_loader_criteria(Contract, (Contract.organization_id == org_id) & Contract.client_id.in_(clients), include_aliases=True, propagate_to_loaders=False),
        with_loader_criteria(Payment, Payment.contract_id.in_(contracts), include_aliases=True),
        with_loader_criteria(Installment, Installment.contract_id.in_(contracts), include_aliases=True),
        with_loader_criteria(PaymentPromise, PaymentPromise.client_id.in_(clients), include_aliases=True),
        with_loader_criteria(CollectionNote, CollectionNote.client_id.in_(clients), include_aliases=True),
    )


def install_guards(app):
    @app.before_request
    def authenticated_device():
        endpoint = request.endpoint or ''
        if endpoint in {'static', 'healthz', 'service_worker', 'offline'} or endpoint.startswith('portal.'):
            return None
        if not current_user.is_authenticated:
            return None
        record = getattr(g, 'auth_session_record', None)
        if endpoint.startswith('auth.'):
            return None
        if record is None:
            return redirect(url_for('auth.resume', next=request.full_path.rstrip('?')))
        # A restore from a remember cookie needs a real password before sensitive
        # changes. Ordinary navigation remains convenient; monetary entry itself
        # is not forced to reauthenticate every ten minutes.
        sensitive = endpoint in {
            'ops.reversal_create', 'ops.supplier_reverse', 'ops.controls',
            'ops.import_confirm', 'ops.bank_unmatch', 'main.team_add', 'main.team_update', 'main.team_toggle', 'main.team_password',
        } or endpoint.startswith('admin.')
        if request.method not in {'GET', 'HEAD', 'OPTIONS'} and sensitive and not recent_auth():
            if request.is_json or request.path.startswith('/api/'):
                return jsonify(ok=False, error='reauthentication_required', redirect=url_for('auth.resume')), 401
            # Do not replay unsafe POST automatically. The browser can go back
            # to its form after authentication and deliberately submit once.
            from urllib.parse import urlsplit
            from .security_primitives import safe_next
            ref = urlsplit(request.referrer or '')
            # Return only to a same-origin GET form, never the POST-only action.
            target = safe_next(ref.path + ('?' + ref.query if ref.query else ''), url_for('main.settings')) if ref.netloc == request.host else url_for('main.settings')
            flash_message = 'Confirma tu identidad y vuelve a enviar el formulario. No se registro la operacion.'
            from flask import flash
            flash(flash_message, 'info')
            return redirect(url_for('auth.resume', next=target), code=303)
        if current_user.role == 'collector':
            controls = db.session.get(OrganizationControls, current_user.organization_id)
            if controls and controls.collectors_restricted:
                g.collector_scope = (current_user.organization_id, current_user.id)
        return None


def enforce_subscription():
    if (request.endpoint or '').startswith(('auth.', 'portal.')):
        return None
    subscription = current_user.organization.subscription
    if subscription is None:
        # Existing manually managed accounts are not silently locked retroactively.
        return None
    state = subscription.effective_status
    locked = bool(subscription.billing_lock_enabled)
    if not locked and state not in {'expired', 'suspended', 'cancelled'}:
        return None
    if state == 'expired' and not locked and subscription.status == 'active' and subscription.current_period_end:
        today = business_date(utcnow(), current_app.config['APP_TIMEZONE'])
        if today <= subscription.current_period_end + timedelta(days=current_app.config.get('BILLING_GRACE_DAYS', 3)):
            return None
    # Explicit, permission-controlled access to account data after expiry.
    if request.endpoint in {'main.subscription_status', 'main.export_business_data', 'security.index', 'security.revoke', 'security.revoke_others'}:
        return None
    if request.path.startswith('/api/') or request.is_json:
        return jsonify(ok=False, error='subscription_inactive', redirect=url_for('main.subscription_status')), 403
    return redirect(url_for('main.subscription_status'))
