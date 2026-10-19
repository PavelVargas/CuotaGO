"""Read-only readiness checks. A green check is not an integration certificate."""
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


def validate_security_config(config):
    ZoneInfo(config.get('APP_TIMEZONE', 'America/Santo_Domingo'))
    production = config.get('APP_ENV') not in {'local', 'development', 'test'}
    key = config.get('SECRET_KEY', '')
    if not key:
        raise RuntimeError('Falta SECRET_KEY. Configura una clave privada y conserva una copia segura.')
    if production:
        if len(key) < 32 or key in {'missing-secret-key-change-this-immediately', 'change-me', 'dev'}:
            raise RuntimeError('SECRET_KEY de produccion debe ser privada, aleatoria y tener al menos 32 caracteres.')
        if config.get('DEBUG'):
            raise RuntimeError('DEBUG no esta permitido en produccion.')
        if not config.get('SESSION_COOKIE_SECURE') or not config.get('REMEMBER_COOKIE_SECURE'):
            raise RuntimeError('Las cookies deben ser Secure en produccion (HTTPS).')
        if config.get('SECRET_KEY_SOURCE') == 'local-file':
            raise RuntimeError('La clave local no puede utilizarse en produccion.')
        base = config.get('PUBLIC_BASE_URL', '')
        if base and urlsplit(base).scheme != 'https':
            raise RuntimeError('PUBLIC_BASE_URL debe usar HTTPS en produccion.')


def inspect_readiness(app, org_id=None):
    c = app.config
    from .extensions import db
    from .migrations_v83 import is_current
    return [
        ('Esquema v83', 'correcto' if is_current(db.engine) else 'pendiente', 'Migracion aditiva; no recalcula ventas antiguas.'),
        ('Entorno', c.get('APP_ENV', 'local'), 'Usar una base separada y sin clientes reales para depurar.'),
        ('Clave privada', 'configurada' if c.get('SECRET_KEY_SOURCE') == 'environment' else 'local', 'No se muestra el valor. Conservarla para sesiones y segundo factor.'),
        ('Cookies HTTPS', 'activas' if c.get('SESSION_COOKIE_SECURE') else 'solo entorno local', 'HTTPS obligatorio al publicar.'),
        ('Proxy confiable', str(c.get('TRUST_PROXY_COUNT', 0)), 'Configurar solo los proxies reales; nunca confiar en cabeceras arbitrarias.'),
        ('Respaldos', 'requiere ensayo', 'Una exportacion CSV no sustituye una restauracion de PostgreSQL.'),
        ('e-CF', 'no conectado', 'No se emiten comprobantes fiscales electronicos. Requiere proveedor autorizado.'),
        ('Pagos bancarios', 'conciliacion manual', 'Importar extracto no mueve dinero ni verifica una cuenta bancaria en linea.'),
        ('WhatsApp', 'enlaces manuales', 'Sin envio masivo ni automatizacion; revisar elegibilidad y consentimiento.'),
        ('Cobros offline', 'no habilitados', 'La PWA no acepta pagos sin conexion; evita conflictos y duplicados.'),
    ]
