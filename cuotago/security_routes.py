"""Second-factor enrollment and per-device session revocation (owner's own account)."""
import json
import secrets
from datetime import timedelta
from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, logout_user
from .extensions import db
from .business_time import utcnow
from .secure_sessions import check_mfa, start_session
from .security_primitives import (new_totp_secret, encrypt_secret, decrypt_secret, verify_totp,
                                   provisioning_uri, digest)
from .operations.models import UserMFA, UserSession
from .operations.common import audit
from .operations.http import validated_operation

security_bp = Blueprint('security', __name__, url_prefix='/security')


@security_bp.before_request
@login_required
def secure_account():
    return None


def verify_identity(require_mfa=True):
    from .auth import _login_rate_state, _record_login_failure, _clear_login_failures
    key = 'security:' + current_user.email
    ok, minutes = _login_rate_state(key)
    if not ok:
        raise ValueError('Demasiados intentos. Intenta mas tarde.')
    if not current_user.check_password(request.form.get('password', '')):
        _record_login_failure(key)
        raise ValueError('La contrasena no coincide.')
    if require_mfa and not check_mfa(current_user.id, request.form.get('code', '')):
        _record_login_failure(key)
        raise ValueError('Codigo incorrecto, vencido o ya usado.')
    # Failure records are committed independently only when verification failed.
    # On success clear them with the rest of the transaction, not mid-enrollment.
    from .auth import _login_rate_key
    from .models import AuthRateLimit
    if require_mfa:
        AuthRateLimit.query.filter_by(key_hash=_login_rate_key(key)).delete(synchronize_session=False)


@security_bp.get('/')
def index():
    mfa = db.session.get(UserMFA, current_user.id)
    devices = UserSession.query.filter_by(user_id=current_user.id).order_by(UserSession.id.desc()).limit(40).all()
    return render_template('security/index.html', mfa=mfa, devices=devices,
        current_device_id=getattr(getattr(g, 'auth_session_record', None), 'id', None))


@security_bp.post('/mfa/start')
@validated_operation
def enroll_start():
    verify_identity()
    row = UserMFA.query.filter_by(user_id=current_user.id).with_for_update(of=UserMFA).first()
    if row and row.enabled_at:
        raise ValueError('El segundo factor ya esta activo.')
    if row is None:
        row = UserMFA(user_id=current_user.id)
        db.session.add(row)
    secret = new_totp_secret()
    row.encrypted_secret = encrypt_secret(secret, current_app.config['SECRET_KEY'])
    row.setup_expires_at = utcnow() + timedelta(minutes=10)
    row.last_counter = -1
    db.session.commit()
    return render_template('security/enroll.html', secret=secret, uri=provisioning_uri(secret, current_user.email))


@security_bp.post('/mfa/confirm')
@validated_operation
def enroll_confirm():
    verify_identity(require_mfa=False)
    row = UserMFA.query.filter_by(user_id=current_user.id).populate_existing().with_for_update(of=UserMFA).first()
    if not row or row.enabled_at or not row.setup_expires_at or row.setup_expires_at <= utcnow():
        raise ValueError('La configuracion vencio. Inicia nuevamente.')
    secret = decrypt_secret(row.encrypted_secret, current_app.config['SECRET_KEY'])
    counter = verify_totp(secret, request.form.get('code', ''), last_counter=row.last_counter)
    if counter is None:
        from .auth import _record_login_failure
        _record_login_failure('security:' + current_user.email)
        raise ValueError('Codigo de autenticador incorrecto.')
    from .auth import _login_rate_key
    from .models import AuthRateLimit
    AuthRateLimit.query.filter_by(key_hash=_login_rate_key('security:' + current_user.email)).delete(synchronize_session=False)
    codes = [secrets.token_hex(8).upper() for _ in range(10)]
    row.recovery_hashes = json.dumps([digest(code) for code in codes])
    row.enabled_at, row.last_counter = utcnow(), counter
    row.setup_expires_at = None
    current_user.auth_version = (current_user.auth_version or 1) + 1
    UserSession.query.filter_by(user_id=current_user.id, revoked_at=None).update({'revoked_at': utcnow()})
    audit(db.session, current_user.organization_id, current_user.id, 'security.mfa_enabled', 'user', current_user.id, 'Segundo factor habilitado. Sesiones anteriores revocadas.')
    db.session.commit()
    start_session(current_user._get_current_object())
    return render_template('security/recovery.html', codes=codes)


@security_bp.post('/mfa/disable')
@validated_operation
def disable():
    verify_identity()
    row = db.session.get(UserMFA, current_user.id)
    if not row or not row.enabled_at:
        raise ValueError('El segundo factor no esta activo.')
    db.session.delete(row)
    current_user.auth_version = (current_user.auth_version or 1) + 1
    UserSession.query.filter_by(user_id=current_user.id, revoked_at=None).update({'revoked_at': utcnow()})
    audit(db.session, current_user.organization_id, current_user.id, 'security.mfa_disabled', 'user', current_user.id, 'Segundo factor deshabilitado con verificacion de identidad.')
    db.session.commit()
    start_session(current_user._get_current_object())
    return redirect(url_for('security.index'))


@security_bp.post('/devices/<int:device_id>/revoke')
@validated_operation
def revoke(device_id):
    verify_identity()
    record = UserSession.query.filter_by(id=device_id, user_id=current_user.id).with_for_update(of=UserSession).first_or_404()
    record.revoked_at = utcnow()
    audit(db.session, current_user.organization_id, current_user.id, 'security.session_revoked', 'user_session', record.id, 'Dispositivo revocado.')
    db.session.commit()
    if record.id == getattr(getattr(g, 'auth_session_record', None), 'id', None):
        logout_user()
        session.clear()
        return redirect(url_for('auth.login'))
    return redirect(url_for('security.index'))


@security_bp.post('/devices/revoke-others')
@validated_operation
def revoke_others():
    verify_identity()
    record = getattr(g, 'auth_session_record', None)
    q = UserSession.query.filter_by(user_id=current_user.id, revoked_at=None)
    if record:
        q = q.filter(UserSession.id != record.id)
    q.update({'revoked_at': utcnow()}, synchronize_session=False)
    audit(db.session, current_user.organization_id, current_user.id, 'security.other_sessions_revoked', 'user', current_user.id, 'Otros dispositivos revocados.')
    db.session.commit()
    return redirect(url_for('security.index'))
