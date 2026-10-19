"""Forward-only PostgreSQL schema upgrade. No historical money UPDATE/DELETE."""
from sqlalchemy import text, inspect
VERSION = '2026-10-v183-preproduction'
COLUMNS = {
    'users': ['auth_version INTEGER NOT NULL DEFAULT 1'],
    'clients': ['assigned_collector_id INTEGER REFERENCES users(id)', 'import_key VARCHAR(64)'],
    'assets': ['is_virtual BOOLEAN NOT NULL DEFAULT FALSE'],
    'contracts': ['inventory_unit_cost NUMERIC(12,2)', 'inventory_released BOOLEAN NOT NULL DEFAULT FALSE',
                  'opening_paid NUMERIC(12,2) NOT NULL DEFAULT 0', 'imported_on DATE'],
    'installments': ['late_fee_reset_on DATE'],
    'payments': ['voided_at TIMESTAMP', 'voided_by_user_id INTEGER', 'void_reason VARCHAR(240)',
                 'allocation_version INTEGER NOT NULL DEFAULT 0'],
}
INDEXES = [
    'CREATE UNIQUE INDEX IF NOT EXISTS ix_clients_import_key ON clients (import_key)',
    'CREATE INDEX IF NOT EXISTS ix_clients_collector ON clients (organization_id, assigned_collector_id)',
    'CREATE INDEX IF NOT EXISTS ix_payments_contract_time ON payments (contract_id, paid_at)',
    'CREATE INDEX IF NOT EXISTS ix_purchases_org_day ON purchases (organization_id, purchase_date)',
]


def _migrate_v83(engine):
    from .extensions import db
    from .operations import models
    if engine.dialect.name != 'postgresql':
        raise RuntimeError('La migracion v83 requiere PostgreSQL.')
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(18320261019)"))
        conn.execute(text("SET LOCAL lock_timeout = '10s'"))
        conn.execute(text('CREATE TABLE IF NOT EXISTS cuotago_schema_migrations (version VARCHAR(80) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)'))
        if conn.execute(text('SELECT 1 FROM cuotago_schema_migrations WHERE version=:v'), {'v': VERSION}).scalar():
            return False
        for table, definitions in COLUMNS.items():
            for definition in definitions:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {definition}'))
        # New tables only. create_all never alters or copies legacy monetary data.
        db.metadata.create_all(conn)
        for stmt in INDEXES:
            conn.execute(text(stmt))
        conn.execute(text('INSERT INTO cuotago_schema_migrations(version) VALUES (:v)'), {'v': VERSION})
    return True


def _is_v83_current(engine):
    if not inspect(engine).has_table('cuotago_schema_migrations'):
        return False
    with engine.connect() as c:
        return bool(c.execute(text('SELECT 1 FROM cuotago_schema_migrations WHERE version=:v'), {'v': VERSION}).scalar())


def migrate(engine):
    # Keep the established launcher/CLI compatible; upgrading v83 also applies
    # the additive order-editor migration, even when v83 was already recorded.
    changed = _migrate_v83(engine)
    from .migrations_v84 import migrate as migrate_orders
    return migrate_orders(engine) or changed


def is_current(engine):
    from .migrations_v84 import is_current as orders_current
    return _is_v83_current(engine) and orders_current(engine)


def assert_current(engine):
    if not is_current(engine):
        raise RuntimeError('Falta preparar el esquema de preproduccion v84. Hacer respaldo y ejecutar: flask --app tools.maintenance_app migrate-v83. No se modifico la base.')
