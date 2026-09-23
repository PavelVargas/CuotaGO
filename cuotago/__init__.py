from pathlib import Path
import time

from flask import Flask, flash, g, jsonify, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user, logout_user
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import text

from config import Config
from .extensions import compress, csrf, db, login_manager


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
        "ALTER TABLE installments ADD COLUMN IF NOT EXISTS late_fee_base_amount NUMERIC(12,2) NOT NULL DEFAULT 0",
        "ALTER TABLE installments ADD COLUMN IF NOT EXISTS late_fee_paid NUMERIC(12,2) NOT NULL DEFAULT 0",
        "ALTER TABLE installments ADD COLUMN IF NOT EXISTS principal_paid_at TIMESTAMP NULL",
        "ALTER TABLE payments ADD COLUMN IF NOT EXISTS late_fee_amount NUMERIC(12,2) NOT NULL DEFAULT 0",
        "ALTER TABLE payments ADD COLUMN IF NOT EXISTS reference VARCHAR(120)",
        "ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_kind VARCHAR(24) NOT NULL DEFAULT 'payment'",
        "ALTER TABLE payments ADD COLUMN IF NOT EXISTS receipt_code VARCHAR(60)",
        "ALTER TABLE payments ADD COLUMN IF NOT EXISTS created_by_user_id INTEGER NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_payments_receipt_code ON payments (receipt_code) WHERE receipt_code IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_payments_created_by_user_id ON payments (created_by_user_id)",
        """CREATE TABLE IF NOT EXISTS collection_notes (
            id SERIAL PRIMARY KEY,
            organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            contract_id INTEGER REFERENCES contracts(id) ON DELETE SET NULL,
            body TEXT NOT NULL,
            created_by_user_id INTEGER,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_collection_notes_organization_id ON collection_notes (organization_id)",
        "CREATE INDEX IF NOT EXISTS ix_collection_notes_client_id ON collection_notes (client_id)",
        "CREATE INDEX IF NOT EXISTS ix_collection_notes_contract_id ON collection_notes (contract_id)",
        "CREATE INDEX IF NOT EXISTS ix_collection_notes_created_at ON collection_notes (created_at)",
        """CREATE TABLE IF NOT EXISTS payment_promises (
            id SERIAL PRIMARY KEY,
            organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            contract_id INTEGER REFERENCES contracts(id) ON DELETE CASCADE,
            promised_date DATE NOT NULL,
            amount NUMERIC(12,2) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            note VARCHAR(240),
            created_by_user_id INTEGER,
            fulfilled_payment_id INTEGER,
            fulfilled_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_payment_promises_organization_id ON payment_promises (organization_id)",
        "CREATE INDEX IF NOT EXISTS ix_payment_promises_client_id ON payment_promises (client_id)",
        "CREATE INDEX IF NOT EXISTS ix_payment_promises_contract_id ON payment_promises (contract_id)",
        "CREATE INDEX IF NOT EXISTS ix_payment_promises_promised_date ON payment_promises (promised_date)",
        "CREATE INDEX IF NOT EXISTS ix_payment_promises_status ON payment_promises (status)",
        """CREATE TABLE IF NOT EXISTS contract_schedule_changes (
            id SERIAL PRIMARY KEY,
            organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
            created_by_user_id INTEGER,
            reason VARCHAR(240),
            old_frequency VARCHAR(20),
            new_frequency VARCHAR(20),
            old_next_due_date DATE,
            new_next_due_date DATE,
            old_open_count INTEGER NOT NULL DEFAULT 0,
            new_open_count INTEGER NOT NULL DEFAULT 0,
            pending_principal NUMERIC(12,2) NOT NULL DEFAULT 0,
            pending_late_fee NUMERIC(12,2) NOT NULL DEFAULT 0,
            snapshot TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_contract_schedule_changes_organization_id ON contract_schedule_changes (organization_id)",
        "CREATE INDEX IF NOT EXISTS ix_contract_schedule_changes_contract_id ON contract_schedule_changes (contract_id)",
        "CREATE INDEX IF NOT EXISTS ix_contract_schedule_changes_created_at ON contract_schedule_changes (created_at)",
        """CREATE TABLE IF NOT EXISTS expenses (
            id SERIAL PRIMARY KEY,
            organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            expense_date DATE NOT NULL DEFAULT CURRENT_DATE,
            category VARCHAR(60) NOT NULL DEFAULT 'other',
            amount NUMERIC(12,2) NOT NULL,
            method VARCHAR(30) NOT NULL DEFAULT 'cash',
            reference VARCHAR(120),
            note VARCHAR(240),
            created_by_user_id INTEGER,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_expenses_organization_id ON expenses (organization_id)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_expense_date ON expenses (expense_date)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_category ON expenses (category)",
        """CREATE TABLE IF NOT EXISTS tenant_audit_logs (
            id SERIAL PRIMARY KEY,
            organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            actor_user_id INTEGER,
            action VARCHAR(60) NOT NULL,
            entity_type VARCHAR(40) NOT NULL,
            entity_id VARCHAR(80),
            summary VARCHAR(240) NOT NULL,
            detail TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_tenant_audit_logs_organization_id ON tenant_audit_logs (organization_id)",
        "CREATE INDEX IF NOT EXISTS ix_tenant_audit_logs_actor_user_id ON tenant_audit_logs (actor_user_id)",
        "CREATE INDEX IF NOT EXISTS ix_tenant_audit_logs_action ON tenant_audit_logs (action)",
        "CREATE INDEX IF NOT EXISTS ix_tenant_audit_logs_entity_type ON tenant_audit_logs (entity_type)",
        "CREATE INDEX IF NOT EXISTS ix_tenant_audit_logs_created_at ON tenant_audit_logs (created_at)",
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

    hardening_statements = [
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP NULL",
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS cancelled_by_user_id INTEGER NULL",
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS cancel_reason VARCHAR(240)",
        "CREATE INDEX IF NOT EXISTS ix_contracts_cancelled_at ON contracts (cancelled_at)",
        "CREATE INDEX IF NOT EXISTS ix_contracts_cancelled_by_user_id ON contracts (cancelled_by_user_id)",
        "CREATE INDEX IF NOT EXISTS ix_contracts_org_status_created ON contracts (organization_id, status, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_clients_org_name ON clients (organization_id, full_name)",
        "CREATE INDEX IF NOT EXISTS ix_installments_contract_due ON installments (contract_id, due_date)",
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS voided_at TIMESTAMP NULL",
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS voided_by_user_id INTEGER NULL",
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS void_reason VARCHAR(240) NULL",
        "CREATE INDEX IF NOT EXISTS ix_expenses_voided_at ON expenses (voided_at)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_voided_by_user_id ON expenses (voided_by_user_id)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_org_date ON expenses (organization_id, expense_date DESC)",
        """CREATE TABLE IF NOT EXISTS auth_rate_limits (
            id SERIAL PRIMARY KEY,
            key_hash VARCHAR(64) NOT NULL UNIQUE,
            attempts INTEGER NOT NULL DEFAULT 0,
            window_started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            blocked_until TIMESTAMP NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_auth_rate_limits_key_hash ON auth_rate_limits (key_hash)",
        "CREATE INDEX IF NOT EXISTS ix_auth_rate_limits_blocked_until ON auth_rate_limits (blocked_until)",
        # Convert every legacy initial into a normal auditable payment.  The
        # original contracts.down_payment value remains as plan metadata.
        """INSERT INTO payments (contract_id, amount, late_fee_amount, method, reference, payment_kind, receipt_code, created_by_user_id, note, paid_at)
        SELECT c.id, c.down_payment, 0, 'other', NULL, 'down_payment',
               'CGI-LEGACY-' || c.organization_id::text || '-' || LPAD(c.id::text, 6, '0'),
               NULL, 'Inicial migrada automáticamente', COALESCE(c.created_at, CURRENT_TIMESTAMP)
        FROM contracts c
        WHERE c.down_payment > 0
          AND NOT EXISTS (SELECT 1 FROM payments p WHERE p.contract_id = c.id AND p.payment_kind = 'down_payment')""",
    ]

    performance_statements = [
        # v1.16 used ``voided`` internally. Some databases already carry the
        # v116 migration marker, so v1.17 must heal that schema explicitly.
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP NULL",
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS cancelled_by_user_id INTEGER NULL",
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS cancel_reason VARCHAR(240)",
        "CREATE INDEX IF NOT EXISTS ix_contracts_cancelled_at ON contracts (cancelled_at)",
        "CREATE INDEX IF NOT EXISTS ix_contracts_cancelled_by_user_id ON contracts (cancelled_by_user_id)",
        """DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='contracts' AND column_name='voided_at') THEN
                EXECUTE 'UPDATE contracts SET status=''cancelled'', cancelled_at=COALESCE(cancelled_at, voided_at), cancelled_by_user_id=COALESCE(cancelled_by_user_id, voided_by_user_id), cancel_reason=COALESCE(cancel_reason, void_reason) WHERE status=''voided''';
            END IF;
        END $$""",
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS voided_at TIMESTAMP NULL",
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS voided_by_user_id INTEGER NULL",
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS void_reason VARCHAR(240) NULL",
        "CREATE INDEX IF NOT EXISTS ix_expenses_voided_at ON expenses (voided_at)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_voided_by_user_id ON expenses (voided_by_user_id)",
        "ALTER TABLE assets ADD COLUMN IF NOT EXISTS image_thumb_data BYTEA",
        "ALTER TABLE assets ADD COLUMN IF NOT EXISTS image_updated_at TIMESTAMP NULL",
        "UPDATE assets SET image_updated_at = COALESCE(created_at, CURRENT_TIMESTAMP) WHERE image_data IS NOT NULL AND image_updated_at IS NULL",
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS request_key VARCHAR(64)",
        "ALTER TABLE payments ADD COLUMN IF NOT EXISTS request_key VARCHAR(64)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_contracts_request_key ON contracts (request_key) WHERE request_key IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_payments_request_key ON payments (request_key) WHERE request_key IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_contracts_org_client_status ON contracts (organization_id, client_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_contracts_org_asset_status ON contracts (organization_id, asset_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_installments_due_contract ON installments (due_date, contract_id)",
        "CREATE INDEX IF NOT EXISTS ix_installments_open_due ON installments (due_date, contract_id, paid_amount, late_fee_paid)",
        "CREATE INDEX IF NOT EXISTS ix_payments_contract_paid_at ON payments (contract_id, paid_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_payment_promises_org_status_date ON payment_promises (organization_id, status, promised_date)",
        "CREATE INDEX IF NOT EXISTS ix_purchases_org_date ON purchases (organization_id, purchase_date DESC)",
        "CREATE INDEX IF NOT EXISTS ix_assets_org_status_created ON assets (organization_id, status, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_clients_org_phone ON clients (organization_id, phone)",
        "CREATE INDEX IF NOT EXISTS ix_clients_org_document ON clients (organization_id, document_id)",
        "CREATE INDEX IF NOT EXISTS ix_tenant_audit_org_created ON tenant_audit_logs (organization_id, created_at DESC)",
    ]


    billing_lock_statements = [
        "ALTER TABLE organization_subscriptions ADD COLUMN IF NOT EXISTS billing_lock_enabled BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE organization_subscriptions ADD COLUMN IF NOT EXISTS billing_lock_started_at TIMESTAMP NULL",
        "ALTER TABLE organization_subscriptions ADD COLUMN IF NOT EXISTS billing_lock_by_user_id INTEGER NULL",
    ]

    with db.engine.begin() as connection:
        # Use a CuotaGo-owned ledger instead of the generic ``schema_migrations``
        # name. Existing installations may already have a table with that name
        # but a different schema (for example ``id``/``name`` instead of
        # ``version``). CREATE TABLE IF NOT EXISTS does not reshape an existing
        # table, so selecting ``version`` from it can prevent the whole app from
        # starting. Never alter or delete that legacy/foreign table.
        connection.execute(text("""CREATE TABLE IF NOT EXISTS cuotago_schema_migrations (
            version VARCHAR(80) PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""))

        # If a previous CuotaGo release successfully used the old generic
        # ledger, import only CuotaGo's known markers. This block is conditional
        # on the legacy table actually exposing a ``version`` column, which
        # makes startup safe for databases like the user's existing PostgreSQL.
        legacy_has_version = connection.execute(text("""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'schema_migrations'
                  AND column_name = 'version'
            )
        """)).scalar()
        if legacy_has_version:
            connection.execute(text("""
                INSERT INTO cuotago_schema_migrations(version)
                SELECT version::text
                FROM schema_migrations
                WHERE version::text IN (
                    '2026-09-v115-features',
                    '2026-09-v116-hardening',
                    '2026-09-v117-performance-r2'
                )
                ON CONFLICT (version) DO NOTHING
            """))

        applied = {
            row[0]
            for row in connection.execute(text("SELECT version FROM cuotago_schema_migrations"))
        }
        if "2026-09-v115-features" not in applied:
            for statement in statements:
                connection.execute(text(statement))
            connection.execute(text("INSERT INTO cuotago_schema_migrations(version) VALUES ('2026-09-v115-features') ON CONFLICT DO NOTHING"))
        if "2026-09-v116-hardening" not in applied:
            for statement in hardening_statements:
                connection.execute(text(statement))
            connection.execute(text("INSERT INTO cuotago_schema_migrations(version) VALUES ('2026-09-v116-hardening') ON CONFLICT DO NOTHING"))
        if "2026-09-v117-performance-r2" not in applied:
            for statement in performance_statements:
                connection.execute(text(statement))
            connection.execute(text("INSERT INTO cuotago_schema_migrations(version) VALUES ('2026-09-v117-performance-r2') ON CONFLICT DO NOTHING"))
        if "2026-09-v1172-billing-lock" not in applied:
            for statement in billing_lock_statements:
                connection.execute(text(statement))
            connection.execute(text("INSERT INTO cuotago_schema_migrations(version) VALUES ('2026-09-v1172-billing-lock') ON CONFLICT DO NOTHING"))


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
    compress.init_app(app)

    from .auth import auth_bp
    from .main import main_bp
    from .push import push_bp
    from .admin import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(push_bp)
    app.register_blueprint(admin_bp)

    @app.before_request
    def start_request_timer():
        g.request_started_at = time.perf_counter()

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
        billing_lock = bool(subscription and getattr(subscription, "billing_lock_enabled", False))
        inactive_status = subscription.effective_status if subscription else "pending"
        if not billing_lock and (subscription is None or inactive_status not in {"suspended", "cancelled", "expired"}):
            return None
        if request.endpoint in {"main.subscription_status", "auth.logout", "static", "service_worker", "offline", "healthz"}:
            return None
        if request.path.startswith("/api/"):
            return jsonify({
                "ok": False,
                "error": "billing_locked" if billing_lock else "subscription_inactive",
                "status": "billing_locked" if billing_lock else inactive_status,
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
        response.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
        return response

    @app.route("/offline")
    def offline():
        return render_template("offline.html"), 200

    @app.after_request
    def security_headers(response):
        started = getattr(g, "request_started_at", None)
        if started is not None:
            duration_ms = max((time.perf_counter() - started) * 1000.0, 0.0)
            response.headers.setdefault("Server-Timing", f"app;dur={duration_ms:.1f}")
            threshold = float(app.config.get("SLOW_REQUEST_MS", 800) or 800)
            if duration_ms >= threshold and request.endpoint not in {"static", "healthz", "service_worker"}:
                app.logger.warning(
                    "slow_request endpoint=%s method=%s path=%s status=%s duration_ms=%.1f",
                    request.endpoint, request.method, request.path, response.status_code, duration_ms,
                )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'self'; frame-ancestors 'self'; form-action 'self'; "
            "img-src 'self' data: blob:; media-src 'self'; connect-src 'self'; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "script-src 'self' 'unsafe-inline'"
        )
        if app.config.get("APP_ENV") not in {"local", "development", "test"} and request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if response.mimetype == "text/html":
            response.headers["Cache-Control"] = "private, no-store, max-age=0, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        elif request.endpoint == "static":
            if request.args.get("v"):
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            elif request.path.endswith(("/app.css", "/app.js", "/manifest.webmanifest")):
                response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
        return response

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("errors/403.html"), 403

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
