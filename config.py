import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def normalize_database_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        user = quote_plus(os.getenv("POSTGRES_USER", "postgres"))
        password = quote_plus(os.getenv("POSTGRES_PASSWORD", ""))
        host = os.getenv("POSTGRES_HOST", "127.0.0.1").strip() or "127.0.0.1"
        port = os.getenv("POSTGRES_PORT", "5432").strip() or "5432"
        database = quote_plus(os.getenv("POSTGRES_DB", "cuotago"))
        url = f"postgresql+psycopg://{user}:{password}@{host}:{port}/{database}"
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://") and "+psycopg" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    if not url.startswith("postgresql+"):
        raise RuntimeError("CuotaGo esta configurado para PostgreSQL. Revisa DATABASE_URL en .env.")
    return url


class Config:
    APP_NAME = os.getenv("APP_NAME", "CuotaGo")
    APP_VERSION = os.getenv("APP_VERSION", "1.17.1")
    APP_ENV = os.getenv("APP_ENV", "local").strip().lower()
    APP_CURRENCY = os.getenv("APP_CURRENCY", "DOP")
    APP_TIMEZONE = os.getenv("APP_TIMEZONE", "America/Santo_Domingo")

    SECRET_KEY = os.getenv("SECRET_KEY", "")
    if not SECRET_KEY:
        # Solo evita que un entorno mal configurado explote antes de mostrar un error claro.
        # El paquete entregado ya incluye una SECRET_KEY real en .env.
        SECRET_KEY = "missing-secret-key-change-this-immediately"

    SQLALCHEMY_DATABASE_URI = normalize_database_url(os.getenv("DATABASE_URL", ""))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": max(60, int(os.getenv("DB_POOL_RECYCLE", "300"))),
        "pool_size": max(1, int(os.getenv("DB_POOL_SIZE", "5"))),
        "max_overflow": max(0, int(os.getenv("DB_MAX_OVERFLOW", "5"))),
    }

    DEBUG = _bool_env("FLASK_DEBUG", False)
    AUTO_CREATE_DB = _bool_env("AUTO_CREATE_DB", True)

    WTF_CSRF_TIME_LIMIT = None
    REMEMBER_COOKIE_DURATION = timedelta(days=max(1, int(os.getenv("REMEMBER_DAYS", "90"))))
    REMEMBER_COOKIE_REFRESH_EACH_REQUEST = True
    REMEMBER_COOKIE_HTTPONLY = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool_env("COOKIE_SECURE", APP_ENV not in {"local", "development", "test"})
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE

    MAX_CONTENT_LENGTH = 16 * 1024 * 1024

    # Static assets are fingerprinted with APP_VERSION in templates. Let browsers
    # keep them aggressively; /service-worker.js is explicitly no-cache.
    SEND_FILE_MAX_AGE_DEFAULT = 31536000

    # Compress HTML/JSON/CSS/JS over mobile networks.
    COMPRESS_MIMETYPES = [
        "text/html", "text/css", "application/javascript", "application/json",
        "image/svg+xml", "text/plain",
    ]
    COMPRESS_LEVEL = 6
    COMPRESS_MIN_SIZE = 1024

    SLOW_REQUEST_MS = max(100, int(os.getenv("SLOW_REQUEST_MS", "800")))

    # Cuenta maestra opcional. En Railway configura estas variables para crear/actualizar
    # automáticamente un superadmin. No se usan credenciales por defecto en producción.
    SUPERADMIN_EMAIL = os.getenv("SUPERADMIN_EMAIL", "").strip().lower()
    SUPERADMIN_PASSWORD = os.getenv("SUPERADMIN_PASSWORD", "")
    SUPERADMIN_NAME = os.getenv("SUPERADMIN_NAME", "Superadmin").strip() or "Superadmin"
    SUPERADMIN_ORG_NAME = os.getenv("SUPERADMIN_ORG_NAME", "CuotaGo Administracion").strip() or "CuotaGo Administracion"

    # Web Push / notificaciones PWA
    VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "").strip()
    VAPID_PRIVATE_KEY_B64 = os.getenv("VAPID_PRIVATE_KEY_B64", "").strip()
    VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:admin@cuotago.app").strip()
    PUSH_NOTIFICATIONS_ENABLED = _bool_env("PUSH_NOTIFICATIONS_ENABLED", True)
    PUSH_SCHEDULER_ENABLED = _bool_env("PUSH_SCHEDULER_ENABLED", True)
    PUSH_CHECK_INTERVAL_MINUTES = max(1, int(os.getenv("PUSH_CHECK_INTERVAL_MINUTES", "5")))
    PUSH_ALERT_START_HOUR = min(23, max(0, int(os.getenv("PUSH_ALERT_START_HOUR", "8"))))
    PUSH_ALERT_END_HOUR = min(24, max(1, int(os.getenv("PUSH_ALERT_END_HOUR", "22"))))
    PUSH_OVERDUE_REPEAT_HOURS = min(2, max(1, int(os.getenv("PUSH_OVERDUE_REPEAT_HOURS", "2"))))
