"""Maintenance entrypoints never connect to any external account."""
import json
import click
from .extensions import db


def register_commands(app):
    @app.cli.command('migrate-v83')
    @click.option('--confirm-production', is_flag=True, help='Requires a verified backup and maintenance window.')
    def migrate_command(confirm_production):
        if app.config.get('APP_ENV') not in {'local', 'development', 'test', 'staging'} and not confirm_production:
            raise click.ClickException('Primero respalda y ensaya en staging. Produccion requiere --confirm-production.')
        from .migrations_v83 import migrate
        # The maintenance factory registers every model, but never creates schema
        # during import. Brand-new databases are initialized explicitly here.
        from sqlalchemy import inspect
        if not inspect(db.engine).has_table('organizations'):
            db.create_all()
        from . import _ensure_feature_schema
        _ensure_feature_schema(app)
        changed = migrate(db.engine)
        click.echo('Esquema de preproduccion v83 + v84 aplicado.' if changed else 'El esquema de preproduccion ya esta actualizado.')

    @app.cli.command('preflight')
    def preflight():
        from .readiness import inspect_readiness
        click.echo(json.dumps(inspect_readiness(app), ensure_ascii=False, indent=2))
