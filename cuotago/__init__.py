from pathlib import Path

from flask import Flask, jsonify, render_template, send_from_directory
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
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS quantity INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS base_amount NUMERIC(12,2) NOT NULL DEFAULT 0",
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS profit_margin_percent NUMERIC(7,2) NOT NULL DEFAULT 0",
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS daily_late_interest NUMERIC(12,2) NOT NULL DEFAULT 0",
        "ALTER TABLE installments ADD COLUMN IF NOT EXISTS late_fee_amount NUMERIC(12,2) NOT NULL DEFAULT 0",
        "ALTER TABLE installments ADD COLUMN IF NOT EXISTS late_fee_paid NUMERIC(12,2) NOT NULL DEFAULT 0",
        "ALTER TABLE installments ADD COLUMN IF NOT EXISTS principal_paid_at TIMESTAMP NULL",
        "ALTER TABLE payments ADD COLUMN IF NOT EXISTS late_fee_amount NUMERIC(12,2) NOT NULL DEFAULT 0",
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
