from flask import Blueprint, flash, redirect, render_template, request, url_for
from datetime import datetime, timedelta
import hashlib

from flask_login import confirm_login, current_user, login_fresh, login_user, logout_user

from .extensions import db
from .models import LoginAttempt, Organization, OrganizationSubscription, User

auth_bp = Blueprint("auth", __name__)


def _login_fingerprint(email):
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    ip = forwarded or request.remote_addr or "unknown"
    raw = f"{email}|{ip}".encode("utf-8", "ignore")
    return hashlib.sha256(raw).hexdigest()


def _login_attempt(email):
    fingerprint = _login_fingerprint(email)
    return LoginAttempt.query.filter_by(fingerprint=fingerprint).first(), fingerprint


def _login_is_blocked(email):
    attempt, _ = _login_attempt(email)
    return bool(attempt and attempt.blocked_until and attempt.blocked_until > datetime.utcnow())


def _register_failed_login(email):
    now = datetime.utcnow()
    attempt, fingerprint = _login_attempt(email)
    if attempt is None:
        attempt = LoginAttempt(fingerprint=fingerprint, failed_count=0, window_started_at=now)
        db.session.add(attempt)
    if not attempt.window_started_at or now - attempt.window_started_at > timedelta(minutes=15):
        attempt.window_started_at = now
        attempt.failed_count = 0
        attempt.blocked_until = None
    attempt.failed_count += 1
    if attempt.failed_count >= 7:
        attempt.blocked_until = now + timedelta(minutes=15)
    db.session.commit()


def _clear_failed_logins(email):
    attempt, _ = _login_attempt(email)
    if attempt is not None:
        db.session.delete(attempt)
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
        remember = request.form.get("remember") == "on"

        if _login_is_blocked(email):
            flash("Demasiados intentos. Intenta nuevamente en unos minutos.", "error")
            return render_template("auth/login.html", email=email), 429

        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            _register_failed_login(email)
            flash("Correo o contraseña incorrectos.", "error")
            return render_template("auth/login.html", email=email)
        if not user.is_enabled:
            flash("Esta cuenta fue deshabilitada. Contacta al administrador.", "error")
            return render_template("auth/login.html", email=email)

        _clear_failed_logins(email)
        user.last_login_at = datetime.utcnow()
        db.session.commit()
        login_user(user, remember=remember)
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
        login_user(user)
        flash("Tu cuenta está lista. Ya puedes empezar.", "success")
        return redirect(url_for("main.dashboard", entered=1))

    return render_template("auth/register.html")


@auth_bp.post("/logout")
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
