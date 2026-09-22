from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from datetime import datetime, timedelta
import hashlib

from flask_login import confirm_login, current_user, login_fresh, login_user, logout_user

from .extensions import db
from .models import AuthRateLimit, Organization, OrganizationSubscription, User

auth_bp = Blueprint("auth", __name__)


LOGIN_WINDOW_MINUTES = 15
LOGIN_MAX_ATTEMPTS = 6
LOGIN_BLOCK_MINUTES = 15


def _login_rate_key(email):
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "unknown").split(",", 1)[0].strip()
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
    row = AuthRateLimit.query.filter_by(key_hash=key_hash).first()
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
    next_url = (request.values.get("next") or "").strip()
    if next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    if current_user.is_authenticated and getattr(current_user, "role", "") == "superadmin":
        return url_for("admin.dashboard")
    return url_for(default_endpoint)


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

        user.last_login_at = datetime.utcnow()
        db.session.commit()
        _clear_login_failures(email)
        login_user(user, remember=True, duration=current_app.config.get("REMEMBER_COOKIE_DURATION"))
        next_url = request.args.get("next", "")
        if next_url.startswith("/") and not next_url.startswith("//"):
            separator = "&" if "?" in next_url else "?"
            return redirect(f"{next_url}{separator}entered=1")
        endpoint = "admin.dashboard" if user.role == "superadmin" else "main.dashboard"
        return redirect(url_for(endpoint, entered=1))

    return render_template("auth/login.html")


@auth_bp.route("/resume", methods=["GET", "POST"])
def resume():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login", next=request.args.get("next", "")))

    if request.method == "POST":
        # UX confirmation for a trusted remembered session. No password is requested by design.
        confirm_login()
        target = _safe_next()
        separator = "&" if "?" in target else "?"
        return redirect(f"{target}{separator}entered=1")

    return render_template("auth/resume.html", next_url=request.args.get("next", ""))


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
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
        subscription = OrganizationSubscription(organization=org, status="pending")
        db.session.add_all([org, user, subscription])
        db.session.commit()
        login_user(user, remember=True, duration=current_app.config.get("REMEMBER_COOKIE_DURATION"))
        flash("Tu cuenta está lista. Ya puedes empezar.", "success")
        return redirect(url_for("main.dashboard", entered=1))

    return render_template("auth/register.html")


@auth_bp.post("/logout")
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
