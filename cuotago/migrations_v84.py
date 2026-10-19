"""Additive order-editor schema. Never alters historical stock or amounts."""
from sqlalchemy import text, inspect
VERSION = '2026-10-v184-purchase-editor'


def migrate(engine):
    if engine.dialect.name != 'postgresql':
        raise RuntimeError('La migracion v84 requiere PostgreSQL.')
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(18420261019)'))
        conn.execute(text("SET LOCAL lock_timeout = '10s'"))
        conn.execute(text('CREATE TABLE IF NOT EXISTS cuotago_schema_migrations (version VARCHAR(80) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)'))
        if conn.execute(text('SELECT 1 FROM cuotago_schema_migrations WHERE version=:v'), {'v': VERSION}).scalar():
            return False
        conn.execute(text('ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS revision INTEGER NOT NULL DEFAULT 1'))
        conn.execute(text('ALTER TABLE purchase_order_lines ADD COLUMN IF NOT EXISTS photo_data BYTEA'))
        conn.execute(text('ALTER TABLE purchase_order_lines ADD COLUMN IF NOT EXISTS photo_mime VARCHAR(80)'))
        conn.execute(text('INSERT INTO cuotago_schema_migrations(version) VALUES (:v)'), {'v': VERSION})
    return True


def is_current(engine):
    if not inspect(engine).has_table('cuotago_schema_migrations'):
        return False
    with engine.connect() as conn:
        return bool(conn.execute(text('SELECT 1 FROM cuotago_schema_migrations WHERE version=:v'), {'v': VERSION}).scalar())
