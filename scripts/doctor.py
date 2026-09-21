from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from cuotago import create_app
from cuotago.extensions import db


def main() -> int:
    env_file = ROOT / ".env"
    if not env_file.exists():
        print("[ERROR] Falta .env")
        return 1

    app = create_app()
    db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    secret = app.config.get("SECRET_KEY", "")

    if not secret or len(secret) < 32:
        print("[ERROR] SECRET_KEY ausente o demasiado corta.")
        return 1

    with app.app_context():
        if db.engine.dialect.name != "postgresql":
            print(f"[ERROR] Motor incorrecto: {db.engine.dialect.name}. CuotaGo debe usar PostgreSQL.")
            return 1
        row = db.session.execute(
            text("SELECT current_database() AS db_name, current_user AS db_user")
        ).mappings().one()
        required = {
            "assets": {"quantity_total", "image_mime", "image_data", "sale_price"},
            "contracts": {"quantity", "daily_late_interest"},
            "installments": {"late_fee_amount", "late_fee_paid", "principal_paid_at"},
            "payments": {"late_fee_amount"},
            "purchases": {"organization_id", "asset_id", "purchase_date", "quantity", "unit_cost", "unit_sale_price"},
        }
        missing = []
        for table_name, expected in required.items():
            rows = db.session.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=:table_name"
            ), {"table_name": table_name}).scalars().all()
            present = set(rows)
            for column in sorted(expected - present):
                missing.append(f"{table_name}.{column}")
        db.session.commit()
        if missing:
            print("[ERROR] Faltan columnas/tablas v1.14.0: " + ", ".join(missing))
            return 1

    try:
        import pywebpush  # noqa: F401
        import apscheduler  # noqa: F401
    except ImportError as exc:
        print(f"[ERROR] Dependencia de notificaciones faltante: {exc}")
        return 1

    if app.config.get("PUSH_NOTIFICATIONS_ENABLED"):
        if not app.config.get("VAPID_PUBLIC_KEY") or not app.config.get("VAPID_PRIVATE_KEY_B64"):
            print("[ERROR] Faltan claves VAPID para Web Push.")
            return 1

    masked_db = db_uri
    if "@" in masked_db and "://" in masked_db:
        prefix, rest = masked_db.split("://", 1)
        if "@" in rest:
            creds, host = rest.rsplit("@", 1)
            user = creds.split(":", 1)[0]
            masked_db = f"{prefix}://{user}:***@{host}"

    print("[OK] .env cargado")
    print(f"[OK] PostgreSQL conectado: {masked_db}")
    print(f"[OK] Base: {row['db_name']} | Usuario: {row['db_user']}")
    print(f"[OK] App: {app.config.get('APP_NAME')} v{app.config.get('APP_VERSION')}")
    print("[OK] Esquema: compras, inventario, fotos e intereses OK")
    print("[OK] Web Push: VAPID + scheduler configurados")
    print("[OK] CuotaGo esta listo para iniciar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
