from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for, session
from datetime import datetime, timedelta
import hashlib

from flask_login import confirm_login, current_user, login_fresh, login_user, logout_user

from .extensions import db
from .business_time import business_date, utcnow
from .secure_sessions import start_session, mfa_enabled, check_mfa
from .security_primitives import safe_next
from .models import AuthRateLimit, Organization, OrganizationSubscription, User

auth_bp = Blueprint("auth", __name__)


LOGIN_WINDOW_MINUTES = 15
LOGIN_MAX_ATTEMPTS = 6
LOGIN_BLOCK_MINUTES = 15


def _login_rate_key(email):
    ip = "account"  # Account-wide: spoofed X-Forwarded-For cannot reset the counter.
    secret = current_app.config.get("SECRET_KEY", "")
    raw = f"{email.lower()}|{ip}|{secret}".encode("utf-8", "ignore")
    return hashlib.sha256(raw).hexdigest()


def _login_rate_state(email):
    now = datetime.utcnow()
    key_hash = _login_rate_key(email)
    row = AuthRateLimit.query.filter_by(key_hash=key_hash).first()
    if not row:
        return True, None
    if row.blocked_until and row.blocked_until > now:
        minutes = max(1, int((row.blocked_until - now).total_seconds() // 60) + 1)
        return False, minutes
    if now - row.window_started_at > timedelta(minutes=LOGIN_WINDOW_MINUTES):
        row.attempts = 0
        row.window_started_at = now
        row.blocked_until = None
        db.session.commit()
    return True, None


def _record_login_failure(email):
    now = datetime.utcnow()
    key_hash = _login_rate_key(email)
    # Serialize failures for the same account across worker processes.
    if db.engine.dialect.name == "postgresql":
        from sqlalchemy import text
        db.session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": int(key_hash[:15], 16)})
    row = AuthRateLimit.query.filter_by(key_hash=key_hash).populate_existing().with_for_update(of=AuthRateLimit).first()
    if row is None:
        row = AuthRateLimit(key_hash=key_hash, attempts=0, window_started_at=now)
        db.session.add(row)
    elif now - row.window_started_at > timedelta(minutes=LOGIN_WINDOW_MINUTES):
        row.attempts = 0
        row.window_started_at = now
        row.blocked_until = None
    row.attempts += 1
    if row.attempts >= LOGIN_MAX_ATTEMPTS:
        row.blocked_until = now + timedelta(minutes=LOGIN_BLOCK_MINUTES)
    db.session.commit()


def _clear_login_failures(email):
    key_hash = _login_rate_key(email)
    AuthRateLimit.query.filter_by(key_hash=key_hash).delete(synchronize_session=False)
    db.session.commit()


def _safe_next(default_endpoint="main.dashboard"):
    default = url_for("admin.dashboard" if current_user.is_authenticated and current_user.role == "superadmin" else default_endpoint)
    return safe_next(request.values.get("next"), default)


def _finish_or_challenge(user, target):
    if mfa_enabled(user.id):
        session.clear()
        session["mfa_pending_user"] = user.id
        session["mfa_pending_version"] = user.auth_version
        session["mfa_pending_until"] = (utcnow() + timedelta(minutes=5)).isoformat()
        session["mfa_next"] = target
        return redirect(url_for("auth.mfa"))
    start_session(user)
    return redirect(target)


@auth_bp.route("/mfa", methods=["GET", "POST"])
def mfa():
    uid = session.get("mfa_pending_user")
    deadline = session.get("mfa_pending_until", "")
    try:
        valid = bool(uid and datetime.fromisoformat(deadline) > utcnow())
    except (ValueError, TypeError):
        valid = False
    user = db.session.get(User, uid) if valid else None
    if not user or not user.is_enabled or user.auth_version != session.get("mfa_pending_version"):
        session.clear()
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        key = "mfa:" + user.email
        allowed, minutes = _login_rate_state(key)
        if not allowed:
            flash("Demasiados intentos. Intenta mas tarde.", "error")
            return render_template("auth/mfa.html"), 429
        if not check_mfa(user.id, request.form.get("code")):
            _record_login_failure(key)
            flash("Codigo incorrecto, vencido o ya utilizado.", "error")
            return render_template("auth/mfa.html"), 400
        db.session.commit()
        _clear_login_failures(key)
        target = safe_next(session.get("mfa_next"))
        start_session(user)
        return redirect(target)
    return render_template("auth/mfa.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        if not login_fresh():
            return redirect(url_for("auth.resume", next=request.args.get("next", "")))
        return redirect(url_for("admin.dashboard" if current_user.role == "superadmin" else "main.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        allowed, retry_minutes = _login_rate_state(email)
        if not allowed:
            flash(f"Demasiados intentos. Intenta de nuevo en {retry_minutes} min.", "error")
            return render_template("auth/login.html", email=email), 429

        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            _record_login_failure(email)
            flash("Correo o contraseña incorrectos.", "error")
            return render_template("auth/login.html", email=email)
        if not user.is_enabled:
            flash("Esta cuenta fue deshabilitada. Contacta al administrador.", "error")
            return render_template("auth/login.html", email=email)

        _clear_login_failures(email)
        target = safe_next(request.args.get("next"), url_for("admin.dashboard" if user.role == "superadmin" else "main.dashboard", entered=1))
        return _finish_or_challenge(user, target)

    return render_template("auth/login.html")


@auth_bp.route("/resume", methods=["GET", "POST"])
def resume():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login", next=request.args.get("next", "")))

    if request.method == "POST":
        key = "resume:" + current_user.email
        allowed, minutes = _login_rate_state(key)
        if not allowed:
            flash("Demasiados intentos. Intenta mas tarde.", "error")
            return render_template("auth/resume.html", next_url=request.args.get("next", "")), 429
        if not current_user.check_password(request.form.get("password", "")):
            _record_login_failure(key)
            flash("La contrasena no coincide.", "error")
            return render_template("auth/resume.html", next_url=request.form.get("next", "")), 400
        _clear_login_failures(key)
        return _finish_or_challenge(current_user._get_current_object(), _safe_next())

    return render_template("auth/resume.html", next_url=request.args.get("next", ""))


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if not current_app.config.get("REGISTRATION_ENABLED", True):
        return render_template("auth/login.html"), 403
    if current_user.is_authenticated:
        return redirect(url_for("admin.dashboard" if current_user.role == "superadmin" else "main.dashboard"))

    if request.method == "POST":
        business_name = request.form.get("business_name", "").strip()
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        errors = []
        if len(business_name) < 2:
            errors.append("Escribe el nombre del negocio.")
        if len(name) < 2:
            errors.append("Escribe tu nombre.")
        if "@" not in email or "." not in email:
            errors.append("Escribe un correo válido.")
        if len(password) < 8:
            errors.append("La contraseña debe tener al menos 8 caracteres.")
        if password != confirm:
            errors.append("Las contraseñas no coinciden.")
        if User.query.filter_by(email=email).first():
            errors.append("Ese correo ya está registrado.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "auth/register.html",
                business_name=business_name,
                name=name,
                email=email,
            )

        org = Organization(name=business_name, currency="DOP")
        user = User(organization=org, name=name, email=email, role="owner", is_enabled=True, last_login_at=datetime.utcnow())
        user.set_password(password)
        first_day = business_date(utcnow(), current_app.config.get("APP_TIMEZONE", "America/Santo_Domingo"))
        trial_days = max(1, min(int(current_app.config.get("TRIAL_DAYS", 14)), 90))
        subscription = OrganizationSubscription(organization=org, status="trial",
            current_period_start=first_day, current_period_end=first_day + timedelta(days=trial_days - 1))
        db.session.add_all([org, user, subscription])
        db.session.commit()
        start_session(user)
        flash("Tu cuenta está lista. Ya puedes empezar.", "success")
        return redirect(url_for("main.dashboard", entered=1))

    return render_template("auth/register.html")


@auth_bp.post("/logout")
def logout():
    from flask import g
    record = getattr(g, "auth_session_record", None)
    if record is not None:
        record.revoked_at = utcnow()
        db.session.commit()
    logout_user()
    session.clear()
    return redirect(url_for("auth.login"))
