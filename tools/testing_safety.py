"""Refuse application tests on an unconfirmed or operational database."""
import os
from pathlib import Path
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def operational_url():
    from dotenv import dotenv_values
    values = dotenv_values(ROOT / '.env')
    if values.get('DATABASE_URL'):
        return values['DATABASE_URL']
    if values:
        return 'postgresql://{user}:{password}@{host}:{port}/{database}'.format(
            user=quote(values.get('POSTGRES_USER') or 'postgres', safe=''),
            password=quote(values.get('POSTGRES_PASSWORD') or '', safe=''),
            host=values.get('POSTGRES_HOST') or '127.0.0.1', port=values.get('POSTGRES_PORT') or '5432',
            database=quote(values.get('POSTGRES_DB') or 'cuotago', safe=''))
    return ''


def validate_test_database(url, operational=''):
    from sqlalchemy.engine import make_url
    import re
    try:
        parsed = make_url(url)
    except Exception:
        raise ValueError('Falta una URL PostgreSQL valida para la base de pruebas.') from None
    name = parsed.database or ''
    if parsed.get_backend_name() != 'postgresql':
        raise ValueError('Las pruebas de integracion requieren PostgreSQL.')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{1,55}_(test|qa|staging)', name):
        raise ValueError('La base de pruebas debe tener nombre propio terminado en _test, _qa o _staging.')
    if operational:
        try:
            production = make_url(operational)
            # Deliberately strict even on a different hostname (proxy/alias).
            if name == production.database:
                raise ValueError('La base de pruebas coincide por nombre con la configuracion operativa. Usa otra base.')
        except ValueError:
            raise
        except Exception:
            raise ValueError('No se pudo verificar la separacion de la base operativa.') from None
    return parsed.set(drivername='postgresql+psycopg')


def require_test_database():
    if os.environ.get('CUOTAGO_RUN_PG_TESTS') != '1':
        raise ValueError('Las pruebas PostgreSQL requieren CUOTAGO_RUN_PG_TESTS=1.')
    dsn = os.environ.get('TEST_DATABASE_URL', '')
    return validate_test_database(dsn, operational_url())
