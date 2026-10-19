"""Revocable, per-device login tokens layered over Flask-Login signed cookies."""
import json
from datetime import timedelta, timezone
from flask import current_app, g, has_request_context, request, session
from flask_login import login_user
from sqlalchemy.orm import joinedload
from .extensions import db
from .models import User, Organization
from .operations.models import UserSession, UserMFA
from .business_time import utcnow
from .security_primitives import new_token, digest, decrypt_secret, verify_totp


def resolve_login_id(login_id):
    try:
        parts = str(login_id).split(':')
        user = db.session.get(User, int(parts[0]), options=[joinedload(User.organization).joinedload(Organization.subscription)])
        if user is None or not user.is_enabled:
            return None
        # Legacy cookies only reach /resume; access to business pages is denied
        # by the application guard until password/MFA is actually verified.
        if len(parts) == 1:
            return user
        if len(parts) != 3 or int(parts[1]) != (user.auth_version or 1):
            return None
        record = UserSession.query.filter_by(user_id=user.id, token_hash=digest(parts[2])).first()
        if not record or record.revoked_at or record.expires_at <= utcnow():
            return None
        if has_request_context():
            g.auth_session_record = record
            session['auth_sid'] = parts[2]
        return user
    except (TypeError, ValueError, OverflowError):
        return None


def start_session(user, *, remember=True):
    token = new_token()
    session.clear()
    now = utcnow()
    session['auth_sid'] = token
    session['auth_verified_at'] = now.replace(tzinfo=timezone.utc).timestamp()
    # Absolute maximum expiry: activity cannot extend a revoked/expired token.
    duration = current_app.config.get('REMEMBER_COOKIE_DURATION', timedelta(days=30))
    record = UserSession(user_id=user.id, token_hash=digest(token),
              label=(request.user_agent.string or 'Navegador')[:200],
              created_at=now, last_seen_at=now, expires_at=now + duration)
    db.session.add(record)
    user.last_login_at = now
    db.session.commit()
    login_user(user, remember=remember, duration=duration, fresh=True)
    g.auth_session_record = record
    return record


def recent_auth(seconds=600):
    from datetime import timezone
    try:
        # Store an epoch explicitly as UTC; naive .timestamp depends on server TZ.
        return utcnow().replace(tzinfo=timezone.utc).timestamp() - float(session.get('auth_verified_at', 0)) < seconds
    except (ValueError, TypeError):
        return False


def mfa_enabled(user_id):
    item = db.session.get(UserMFA, user_id)
    return bool(item and item.enabled_at)


def check_mfa(user_id, code):
    row = UserMFA.query.filter_by(user_id=user_id).populate_existing().with_for_update(of=UserMFA).first()
    if not row or not row.enabled_at:
        return True
    code = (code or '').strip()
    try:
        secret = decrypt_secret(row.encrypted_secret, current_app.config['SECRET_KEY'])
    except Exception:
        current_app.logger.error('mfa_decryption_failed user_id=%s; restore the correct master key', user_id)
        return False
    counter = verify_totp(secret, code, last_counter=row.last_counter)
    if counter is not None:
        row.last_counter = counter
        return True
    hashes = json.loads(row.recovery_hashes or '[]')
    normalized = code.replace('-', '').replace(' ', '').upper()
    code_hash = digest(normalized)
    import hmac
    match = next((h for h in hashes if hmac.compare_digest(h, code_hash)), None)
    if match:
        hashes.remove(match)
        row.recovery_hashes = json.dumps(hashes)
        return True
    return False
