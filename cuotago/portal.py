"""Revocable read-only customer portal. Tokens never appear in request URLs."""
from datetime import timedelta
from flask import Blueprint, abort, current_app, jsonify, render_template, request, session, redirect, url_for
from .extensions import db
from .business_time import utcnow, business_date
from .security_primitives import digest
from .models import Client, Contract, Payment, Organization
from .operations.models import PortalGrant

portal_bp = Blueprint('portal', __name__, url_prefix='/portal')


@portal_bp.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'private, no-store, max-age=0'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    return response


@portal_bp.get('')
def entry():
    return render_template('portal/entry.html')


@portal_bp.post('/access')
def access():
    token = request.form.get('token', '')
    if len(token) != 43 or not token.replace('_', '').replace('-', '').isalnum():
        abort(404)
    grant = PortalGrant.query.filter_by(token_hash=digest(token)).first()
    now = utcnow()
    if not grant or grant.revoked_at or grant.expires_at <= now:
        abort(404)
    # This does not log in to the business app or replace its signed auth token.
    session['portal_grant'] = grant.id
    session['portal_until'] = (now + timedelta(minutes=30)).isoformat()
    return redirect(url_for('portal.statement'))


def active_grant():
    from datetime import datetime
    try:
        valid = datetime.fromisoformat(session.get('portal_until', '')) > utcnow()
    except (ValueError, TypeError):
        valid = False
    grant = db.session.get(PortalGrant, session.get('portal_grant')) if valid else None
    if not grant or grant.revoked_at or grant.expires_at <= utcnow():
        session.pop('portal_grant', None)
        abort(404)
    return grant


@portal_bp.get('/statement')
def statement():
    grant = active_grant()
    client = Client.query.filter_by(id=grant.client_id, organization_id=grant.organization_id).first_or_404()
    contracts = Contract.query.filter_by(client_id=client.id, organization_id=grant.organization_id).order_by(Contract.id.desc()).all()
    # Explicit DTO avoids accidentally exposing costs, staff notes or other clients.
    data = []
    for c in contracts:
        data.append(dict(id=c.id, status=c.status, description=c.asset.name, total=str(c.total_amount),
            balance=str(c.balance), principal_paid=str(c.principal_paid_total),
            installments=[dict(due=i.due_date, amount=str(i.amount), remaining=str(i.remaining)) for i in c.installments],
            receipts=[dict(code=p.receipt_code, amount=str(p.amount),
                day=business_date(p.paid_at, current_app.config['APP_TIMEZONE']),
                reversed=bool(p.voided_at)) for p in c.payments]))
    return render_template('portal/statement.html', customer=client.full_name,
        business=db.session.get(Organization, grant.organization_id).name,
        currency=db.session.get(Organization, grant.organization_id).currency, data=data)


@portal_bp.post('/exit')
def exit_portal():
    session.pop('portal_grant', None)
    session.pop('portal_until', None)
    return redirect(url_for('portal.entry'))
