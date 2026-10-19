#!/usr/bin/env python3
"""Encrypted PostgreSQL backups and non-destructive EMPTY test-DB restore.
Needs pg_dump/pg_restore on PATH. Passwords stay in subprocess environment,
not command arguments. The secret backup key is never stored beside the archive.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
from datetime import datetime, timezone
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from sqlalchemy.engine import make_url

MAGIC = b'CGBK83\x01'
CHUNK = 1024 * 1024


def secret_key():
    value = os.environ.get('CUOTAGO_BACKUP_KEY', '')
    try:
        key = bytes.fromhex(value)
    except ValueError:
        key = b''
    if len(key) != 32:
        raise ValueError('CUOTAGO_BACKUP_KEY debe ser una clave privada de 64 caracteres hexadecimales. Usa generate-key y guardala en un gestor seguro.')
    return key


def pg_env(url):
    parsed = make_url(url)
    if not parsed.drivername.startswith('postgresql') and parsed.drivername != 'postgres':
        raise ValueError('Se requiere PostgreSQL.')
    env = os.environ.copy()
    env.update(PGHOST=parsed.host or '127.0.0.1', PGPORT=str(parsed.port or 5432),
               PGUSER=parsed.username or 'postgres', PGPASSWORD=parsed.password or '', PGDATABASE=parsed.database or '')
    # No ambient options/search_path from an unrelated shell session.
    env.pop('PGOPTIONS', None)
    if parsed.query.get('sslmode'):
        env['PGSSLMODE'] = str(parsed.query['sslmode'])
    return env


def backup(url, destination, key):
    target = Path(destination).resolve()
    if target.exists():
        raise ValueError('El archivo ya existe; no se sobrescribe.')
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + '.partial-' + secrets.token_hex(4))
    nonce = secrets.token_bytes(12)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(MAGIC)
    process = None
    try:
        with tempfile.TemporaryFile() as errors, partial.open('xb') as out:
            try: partial.chmod(0o600)
            except OSError: pass
            out.write(MAGIC + nonce)
            process = subprocess.Popen(['pg_dump', '--format=custom', '--no-owner', '--no-privileges'],
                env=pg_env(url), stdout=subprocess.PIPE, stderr=errors)
            for chunk in iter(lambda: process.stdout.read(CHUNK), b''):
                out.write(encryptor.update(chunk))
            if process.wait() != 0:
                # Do not copy stderr containing connection details into reports.
                raise RuntimeError('pg_dump fallo. Verifica acceso, version de cliente y permisos; no se creo un respaldo valido.')
            out.write(encryptor.finalize());out.write(encryptor.tag)
            out.flush();os.fsync(out.fileno())
        # No overwrite even in a race with a second backup job.
        os.link(partial, target)
        partial.unlink()
        checksum = file_sha(target)
        meta = dict(format='CuotaGO-encrypted-pgdump-v83', created_utc=datetime.now(timezone.utc).isoformat(),sha256=checksum,
                    encrypted=True,restoration_tested=False)
        target.with_suffix(target.suffix+'.json').write_text(json.dumps(meta,indent=2))
        return meta
    finally:
        if process and process.poll() is None:process.kill();process.wait()
        partial.unlink(missing_ok=True)


def file_sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(CHUNK),b''):h.update(chunk)
    return h.hexdigest()


def decrypt_to(source, destination, key):
    """Publish plaintext only after authenticating the complete archive."""
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise ValueError('El destino ya existe; no se sobrescribe.')
    size = source.stat().st_size
    if size < len(MAGIC) + 12 + 16:
        raise ValueError('Archivo incompleto.')
    partial = destination.with_name(destination.name + '.partial-' + secrets.token_hex(6))
    try:
        with source.open('rb') as src, partial.open('xb') as dst:
            try: partial.chmod(0o600)
            except OSError: pass
            if src.read(len(MAGIC)) != MAGIC:
                raise ValueError('Formato no reconocido.')
            nonce = src.read(12)
            src.seek(-16, 2); tag = src.read(16); src.seek(len(MAGIC) + 12)
            decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
            decryptor.authenticate_additional_data(MAGIC)
            left = size - len(MAGIC) - 12 - 16
            while left:
                block = src.read(min(CHUNK, left))
                if not block:
                    raise ValueError('Archivo truncado.')
                left -= len(block)
                dst.write(decryptor.update(block))
            dst.write(decryptor.finalize())
            dst.flush(); os.fsync(dst.fileno())
        os.link(partial, destination)
    finally:
        partial.unlink(missing_ok=True)


def assert_safe_test_target(target_url, production_url, confirmation):
    t=make_url(target_url);p=make_url(production_url) if production_url else None
    name=t.database or ''
    if not name.endswith(('_test','_restore')) or confirmation!=name:
        raise ValueError('Destino debe terminar en _test o _restore; confirma exactamente su nombre con --confirm-empty.')
    if t.get_backend_name() != 'postgresql':
        raise ValueError('El destino debe ser PostgreSQL.')
    if p and name == p.database:
        raise ValueError('El destino coincide con DATABASE_URL; se rechazo la restauracion.')


def restore_test(source,target_url,confirmation,key):
    assert_safe_test_target(target_url,os.environ.get('DATABASE_URL',''),confirmation)
    import psycopg
    env=pg_env(target_url)
    kwargs=dict(host=env['PGHOST'],port=env['PGPORT'],user=env['PGUSER'],password=env['PGPASSWORD'],dbname=env['PGDATABASE'])
    if 'PGSSLMODE' in env:kwargs['sslmode']=env['PGSSLMODE']
    with psycopg.connect(**kwargs) as conn:
        n=conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema')").fetchone()[0]
        if n:raise ValueError('La base destino no esta vacia. No se borro nada. Crea otra base exclusiva para el ensayo.')
    with tempfile.TemporaryDirectory(prefix='cuotago-restore-') as tmp:
        archive=Path(tmp)/'backup.dump';decrypt_to(source,archive,key)
        subprocess.run(['pg_restore','--list',str(archive)],check=True,stdout=subprocess.DEVNULL)
        # No --clean, no DROP DATABASE, no production migration.
        subprocess.run(['pg_restore','--no-owner','--no-privileges','--exit-on-error','--single-transaction',
                        '--dbname',env['PGDATABASE'],str(archive)],env=env,check=True)
    return dict(restored_to_test=True, finished_utc=datetime.now(timezone.utc).isoformat(), archive_sha256=file_sha(source))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    sub.add_parser('generate-key')
    b=sub.add_parser('backup');b.add_argument('--out',required=True)
    v=sub.add_parser('verify');v.add_argument('archive')
    r=sub.add_parser('restore-test');r.add_argument('archive');r.add_argument('--confirm-empty',required=True)
    args=parser.parse_args()
    try:
        if args.action=='generate-key':print(secrets.token_hex(32));return 0
        key=secret_key()
        if args.action=='backup':
            url=os.environ.get('DATABASE_URL','')
            if not url:raise ValueError('Falta DATABASE_URL en el entorno.')
            result=backup(url,args.out,key)
        elif args.action=='verify':
            with tempfile.TemporaryDirectory(prefix='cuotago-verify-') as tmp:
                dst=Path(tmp)/'verified.dump';decrypt_to(args.archive,dst,key)
                subprocess.run(['pg_restore','--list',str(dst)],check=True,stdout=subprocess.DEVNULL)
            result={'authentic':True,'sha256':file_sha(args.archive),'restoration_tested':False}
        else:
            target=os.environ.get('RESTORE_TEST_DATABASE_URL','')
            if not target:raise ValueError('Falta RESTORE_TEST_DATABASE_URL.')
            result=restore_test(args.archive,target,args.confirm_empty,key)
        print(json.dumps(result,indent=2));return 0
    except Exception as exc:
        # Exception classes only for database/process failures; no credentials.
        text=str(exc) if isinstance(exc,(ValueError,RuntimeError,FileNotFoundError)) else type(exc).__name__
        print('ERROR:',text);return 1

if __name__=='__main__':raise SystemExit(main())
