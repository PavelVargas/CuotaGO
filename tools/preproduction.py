#!/usr/bin/env python3
"""Local-only, explicit preproduction launcher. Never silently reuse .env's DB."""
import argparse
import getpass
import os
from pathlib import Path
import secrets
import subprocess
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / '.env.preproduction'
sys.path.insert(0, str(ROOT))


def configure():
    from dotenv import dotenv_values
    from tools.testing_safety import validate_test_database, operational_url
    old = dotenv_values(ENV) if ENV.exists() else {}
    if ENV.exists() and input('Ya existe .env.preproduction. Escribe CONFIGURAR para modificarla: ').strip() != 'CONFIGURAR':
        return
    print('Esta configuracion NO utiliza la base de .env. Solo pruebas, sin notificaciones reales.')
    name = input('Nombre de nueva base [cuotago_test]: ').strip() or 'cuotago_test'
    user = input('Usuario PostgreSQL local [postgres]: ').strip() or 'postgres'
    password = getpass.getpass('Contrasena de PostgreSQL local (no se muestra): ')
    port = input('Puerto PostgreSQL local [5432]: ').strip() or '5432'
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError('Puerto no valido.')
    url = f'postgresql+psycopg://{quote(user,safe="")}:{quote(password,safe="")}@127.0.0.1:{port}/{quote(name,safe="")}'
    validate_test_database(url, operational_url())
    # Preserve the staging master key: changing it would invalidate MFA secrets.
    key = old.get('SECRET_KEY') or secrets.token_urlsafe(48)
    text = '\n'.join([
        '# Solo pruebas locales. No subir este archivo a Git.',
        f'DATABASE_URL={url}', f'SECRET_KEY={key}', 'APP_ENV=test',
        'APP_NAME=CuotaGO - Pruebas', 'AUTO_CREATE_DB=0', 'CHECK_SCHEMA_ON_START=1',
        'COOKIE_SECURE=0', 'FLASK_DEBUG=0', 'PUSH_NOTIFICATIONS_ENABLED=0',
        'PUSH_SCHEDULER_ENABLED=0', 'PUBLIC_BASE_URL=http://127.0.0.1:5001',
        'SUPERADMIN_EMAIL=', 'SUPERADMIN_PASSWORD=', 'TRUST_PROXY_COUNT=0',
    ])+'\n'
    ENV.write_text(text, encoding='utf-8')
    try: ENV.chmod(0o600)
    except OSError: pass
    print('Configuracion privada guardada. No se creo ni modifico ninguna base.')


def load_environment():
    from dotenv import dotenv_values
    from tools.testing_safety import validate_test_database, operational_url
    if not ENV.exists():
        configure()
    values = dotenv_values(ENV)
    parsed = validate_test_database(values.get('DATABASE_URL',''), operational_url())
    if parsed.host not in {'localhost','127.0.0.1','::1'}:
        raise ValueError('Este lanzador admite solo PostgreSQL local. Para staging remoto usa el procedimiento documentado.')
    if not values.get('SECRET_KEY') or len(values['SECRET_KEY']) < 32:
        raise ValueError('La configuracion de pruebas necesita su propia SECRET_KEY de al menos 32 caracteres.')
    # Explicit overrides prevent .env, inherited proxy/VAPID settings, and
    # auto-database initialization from turning a test run into a live run.
    os.environ.update({k:str(v) for k,v in values.items() if v is not None})
    os.environ.update(APP_ENV='test', AUTO_CREATE_DB='0', FLASK_DEBUG='0', COOKIE_SECURE='0',
        PUSH_NOTIFICATIONS_ENABLED='0', PUSH_SCHEDULER_ENABLED='0',
        VAPID_PUBLIC_KEY='', VAPID_PRIVATE_KEY_B64='', SUPERADMIN_EMAIL='',
        SUPERADMIN_PASSWORD='', SUPERADMIN_RESYNC='0', TRUST_PROXY_COUNT='0',
        PUBLIC_BASE_URL='http://127.0.0.1:5001', CHECK_SCHEMA_ON_START='1')
    return parsed


def migrate(parsed):
    import psycopg
    from psycopg import sql
    print('Preparacion EXCLUSIVA de:', parsed.database, '(servidor local).')
    confirm = input('Escribe exactamente el nombre de esa base de pruebas para continuar: ').strip()
    if confirm != parsed.database:
        raise ValueError('Confirmacion cancelada; no se modifico la base.')
    kwargs=dict(host=parsed.host,port=parsed.port or 5432,user=parsed.username,password=parsed.password)
    # CREATE only when absent. Never DROP, overwrite, truncate or restore here.
    with psycopg.connect(dbname='postgres',autocommit=True,**kwargs) as conn:
        exists=conn.execute('SELECT 1 FROM pg_database WHERE datname=%s',(parsed.database,)).fetchone()
        if not exists:
            conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(parsed.database)))
    subprocess.run([sys.executable,'-m','flask','--app','tools.maintenance_app','migrate-v83'],cwd=ROOT,check=True)
    print('Base de pruebas preparada. Registra una cuenta de prueba al entrar.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',nargs='?',choices=['run','migrate','tests','preflight','configure'])
    args=parser.parse_args()
    os.chdir(ROOT)
    try:
        action=args.action
        if action is None:
            print('\nCuotaGO 1.27.0-rc1 - PREPRODUCCION (sin despliegue)\n')
            print('1. Iniciar pruebas locales\n2. Preparar / migrar SOLO la base de pruebas\n3. Ejecutar pruebas automatizadas\n4. Verificar configuracion\n5. Configurar conexion local')
            choice=input('Opcion [1]: ').strip() or '1'
            action={'1':'run','2':'migrate','3':'tests','4':'preflight','5':'configure'}.get(choice)
            if not action:raise ValueError('Opcion no valida.')
        if action=='configure':configure();return 0
        parsed=load_environment()
        if action=='migrate':migrate(parsed);return 0
        if action=='tests':
            os.environ['TEST_DATABASE_URL']=parsed.render_as_string(hide_password=False)
            os.environ['CUOTAGO_RUN_PG_TESTS']='1'
            return subprocess.call([sys.executable,str(ROOT/'tools/run_checks.py'),'--postgres'],cwd=ROOT)
        if action=='preflight':
            return subprocess.call([sys.executable,'-m','flask','--app','tools.maintenance_app','preflight'],cwd=ROOT)
        from cuotago import create_app
        app=create_app()
        print('Solo pruebas: http://127.0.0.1:5001 | Ctrl+C para cerrar')
        app.run(host='127.0.0.1',port=5001,debug=False,use_reloader=False)
        return 0
    except KeyboardInterrupt:
        print('\nProceso detenido.');return 0
    except Exception as exc:
        # Connection exceptions can include credentials; do not dump them.
        message=str(exc) if isinstance(exc,(ValueError,RuntimeError)) else type(exc).__name__
        print('ERROR:',message)
        print('Verifica PostgreSQL, dependencias y la base de pruebas. No se cambio .env. Usa opcion 2 solo para preparar pruebas.')
        return 1

if __name__=='__main__':raise SystemExit(main())
