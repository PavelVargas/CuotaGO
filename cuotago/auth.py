from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user

from .extensions import db
from .models import Organization, User

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = request.form.get("remember") == "on"

        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Correo o contraseña incorrectos.", "error")
            return render_template("auth/login.html", email=email)

        login_user(user, remember=remember)
        next_url = request.args.get("next", "")
        if next_url.startswith("/") and not next_url.startswith("//"):
            return redirect(next_url)
        return redirect(url_for("main.dashboard"))

    return render_template("auth/login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

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
        user = User(organization=org, name=name, email=email, role="owner")
        user.set_password(password)
        db.session.add_all([org, user])
        db.session.commit()
        login_user(user)
        flash("Tu cuenta está lista. Ya puedes empezar.", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("auth/register.html")


@auth_bp.post("/logout")
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
