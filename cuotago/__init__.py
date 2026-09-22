from pathlib import Path

from flask import Flask, flash, jsonify, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user, logout_user
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import text

from config import Config
from .extensions import csrf, db, login_manager


def _ensure_feature_schema(app):
    """Small forward-only PostgreSQL upgrade for installs already running on Railway.

    db.create_all() does not add columns to existing tables, so these additions
    are applied explicitly and safely with IF NOT EXISTS.
    """
    statements = [
        "ALTER TABLE assets ADD COLUMN IF NOT EXISTS quantity_total INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE assets ADD COLUMN IF NOT EXISTS image_mime VARCHAR(80)",
        "ALTER TABLE assets ADD COLUMN IF NOT EXISTS image_data BYTEA",
        "ALTER TABLE assets ADD COLUMN IF NOT EXISTS sale_price NUMERIC(12,2) NOT NULL DEFAULT 0",
        """CREATE TABLE IF NOT EXISTS suppliers (
            id SERIAL PRIMARY KEY,
            organization_id INTEGER NOT NULL REFERENCES organizations(id),
            name VARCHAR(140) NOT NULL,
            phone VARCHAR(40),
            notes TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_suppliers_organization_id ON suppliers (organization_id)",
        """CREATE TABLE IF NOT EXISTS purchases (
            id SERIAL PRIMARY KEY,
            organization_id INTEGER NOT NULL REFERENCES organizations(id),
            asset_id INTEGER NOT NULL REFERENCES assets(id),
            supplier_id INTEGER REFERENCES suppliers(id),
            batch_key VARCHAR(36),
            supplier VARCHAR(140),
            reference VARCHAR(120),
            purchase_date DATE NOT NULL DEFAULT CURRENT_DATE,
            quantity INTEGER NOT NULL DEFAULT 1,
            unit_cost NUMERIC(12,2) NOT NULL DEFAULT 0,
            unit_sale_price NUMERIC(12,2) NOT NULL DEFAULT 0,
            notes TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS supplier_id INTEGER REFERENCES suppliers(id)",
        "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS batch_key VARCHAR(36)",
        "CREATE INDEX IF NOT EXISTS ix_purchases_organization_id ON purchases (organization_id)",
        "CREATE INDEX IF NOT EXISTS ix_purchases_asset_id ON purchases (asset_id)",
        "CREATE INDEX IF NOT EXISTS ix_purchases_supplier_id ON purchases (supplier_id)",
        "CREATE INDEX IF NOT EXISTS ix_purchases_batch_key ON purchases (batch_key)",
        "CREATE INDEX IF NOT EXISTS ix_purchases_purchase_date ON purchases (purchase_date)",
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS quantity INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS base_amount NUMERIC(12,2) NOT NULL DEFAULT 0",
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS profit_margin_percent NUMERIC(7,2) NOT NULL DEFAULT 0",
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS daily_late_interest NUMERIC(12,2) NOT NULL DEFAULT 0",
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS late_fee_started_on DATE NULL",
        "ALTER TABLE installments ADD COLUMN IF NOT EXISTS late_fee_amount NUMERIC(12,2) NOT NULL DEFAULT 0",
        "ALTER TABLE installments ADD COLUMN IF NOT EXISTS late_fee_paid NUMERIC(12,2) NOT NULL DEFAULT 0",
        "ALTER TABLE installments ADD COLUMN IF NOT EXISTS principal_paid_at TIMESTAMP NULL",
        "ALTER TABLE payments ADD COLUMN IF NOT EXISTS late_fee_amount NUMERIC(12,2) NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_enabled BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP NULL",
        "ALTER TABLE subscription_payments ADD COLUMN IF NOT EXISTS previous_period_start DATE NULL",
        "ALTER TABLE subscription_payments ADD COLUMN IF NOT EXISTS previous_period_end DATE NULL",
        "ALTER TABLE subscription_payments ADD COLUMN IF NOT EXISTS previous_status VARCHAR(24) NULL",
        "ALTER TABLE subscription_payments ADD COLUMN IF NOT EXISTS voided_at TIMESTAMP NULL",
        "ALTER TABLE subscription_payments ADD COLUMN IF NOT EXISTS voided_by_user_id INTEGER NULL",
        "ALTER TABLE subscription_payments ADD COLUMN IF NOT EXISTS void_reason VARCHAR(240) NULL",
    ]
    if db.engine.dialect.name != "postgresql":
        return
    with db.engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _ensure_superadmin(app):
    """Create or refresh the configured superadmin without hard-coded production credentials."""
    email = (app.config.get("SUPERADMIN_EMAIL") or "").strip().lower()
    password = app.config.get("SUPERADMIN_PASSWORD") or ""
    if not email or not password:
        return
    if len(password) < 10:
        app.logger.warning("SUPERADMIN_PASSWORD debe tener al menos 10 caracteres; superadmin no creado.")
        return

    from .models import Organization, User

    user = User.query.filter_by(email=email).first()
    if user is None:
        organization = Organization(
            name=app.config.get("SUPERADMIN_ORG_NAME", "CuotaGo Administracion"),
            currency=app.config.get("APP_CURRENCY", "DOP"),
        )
        user = User(
            organization=organization,
            name=app.config.get("SUPERADMIN_NAME", "Superadmin"),
            email=email,
            role="superadmin",
        )
        user.set_password(password)
        db.session.add_all([organization, user])
        db.session.commit()
        app.logger.info("Superadmin creado: %s", email)
        return

    changed = False
    if user.role != "superadmin":
        user.role = "superadmin"
        changed = True
    desired_name = app.config.get("SUPERADMIN_NAME", "Superadmin")
    if desired_name and user.name != desired_name:
        user.name = desired_name
        changed = True
    # The configured password is authoritative so Railway can recover access by redeploying.
    if not user.check_password(password):
        user.set_password(password)
        changed = True
    if changed:
        db.session.commit()



def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    # Correcto detrás de Railway/Render/Nginx sin afectar ejecución local.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from .auth import auth_bp
    from .main import main_bp
    from .push import push_bp
    from .admin import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(push_bp)
    app.register_blueprint(admin_bp)

    @app.before_request
    def enforce_account_and_subscription_state():
        if not current_user.is_authenticated:
            return None
        if not getattr(current_user, "is_enabled", True):
            logout_user()
            flash("Tu cuenta fue deshabilitada. Contacta al administrador.", "error")
            return redirect(url_for("auth.login"))
        if getattr(current_user, "role", "") == "superadmin":
            return None
        subscription = getattr(current_user.organization, "subscription", None)
        if subscription is None or subscription.effective_status not in {"suspended", "cancelled", "expired"}:
            return None
        if request.endpoint in {"main.subscription_status", "auth.logout", "static", "service_worker", "offline", "healthz"}:
            return None
        if request.path.startswith("/api/"):
            return jsonify({
                "ok": False,
                "error": "subscription_inactive",
                "status": subscription.effective_status,
                "redirect": url_for("main.subscription_status"),
            }), 403
        return redirect(url_for("main.subscription_status"))

    @app.get("/healthz")
    def healthz():
        try:
            database_name = db.session.execute(text("SELECT current_database()")) .scalar_one()
            db.session.commit()
        except Exception:
            db.session.rollback()
            return jsonify({"ok": False, "database": "error", "version": app.config.get("APP_VERSION")}), 503
        return jsonify({
            "ok": True,
            "database": "postgresql",
            "database_name": database_name,
            "version": app.config.get("APP_VERSION"),
        })

    @app.route("/service-worker.js")
    def service_worker():
        response = send_from_directory(app.static_folder, "service-worker.js")
        response.headers["Service-Worker-Allowed"] = "/"
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.route("/offline")
    def offline():
        return render_template("offline.html"), 200

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(_error):
        db.session.rollback()
        return render_template("errors/500.html"), 500

    if app.config.get("AUTO_CREATE_DB", True):
        with app.app_context():
            db.create_all()
            _ensure_feature_schema(app)
            _ensure_superadmin(app)

    from .push import scan_overdue_and_notify, start_push_scheduler
    start_push_scheduler(app)

    @app.cli.command("notify-overdue")
    def notify_overdue_command():
        """Envia ahora las alertas push de cuotas vencidas pendientes."""
        count = scan_overdue_and_notify(app)
        print(f"Alertas de vencimiento enviadas: {count}")

    return app
