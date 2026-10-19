"""Crypto and safety contract only. Does NOT run pg_dump/restore against a DB."""
from pathlib import Path
import io
import os
import sys
import types
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import postgres_backup as b
from tools.testing_safety import validate_test_database
from cryptography.exceptions import InvalidTag

class Process:
    def __init__(self,data,code=0): self.stdout=io.BytesIO(data);self.code=code
    def wait(self): return self.code
    def poll(self): return self.code
    def kill(self): self.code=-1


def test_backup_roundtrip_no_credential_arguments(tmp_path,monkeypatch):
    data=b'PGDMP\x00'+os.urandom(2100000); calls=[]
    def popen(args,**kw):
        calls.append((args,kw['env']));return Process(data)
    monkeypatch.setattr(b.subprocess,'Popen',popen)
    key=os.urandom(32);target=tmp_path/'copy.cgbk'
    result=b.backup('postgresql://pavel:private-password@127.0.0.1/cuota_test',target,key)
    assert result['encrypted'] and not result['restoration_tested']
    assert 'private-password' not in ' '.join(calls[0][0])
    assert calls[0][1]['PGPASSWORD']=='private-password'
    dest=tmp_path/'read.dump';b.decrypt_to(target,dest,key)
    assert dest.read_bytes()==data
    assert not list(tmp_path.glob('*.partial-*'))
    with pytest.raises(ValueError):b.backup('postgresql://localhost/test',target,key)
    with pytest.raises(ValueError):b.decrypt_to(target,dest,key)


@pytest.mark.parametrize('fault',['key','body','tag','short','format'])
def test_bad_archive_never_publishes_plaintext(tmp_path,monkeypatch,fault):
    monkeypatch.setattr(b.subprocess,'Popen',lambda *a,**kw:Process(b'PGDMP'+os.urandom(10000)))
    key=os.urandom(32);target=tmp_path/'backup'
    b.backup('postgresql://localhost/cuota_test',target,key)
    data=bytearray(target.read_bytes())
    if fault=='key': key=os.urandom(32)
    elif fault=='body':data[40]^=1
    elif fault=='tag':data[-1]^=1
    elif fault=='short':data=data[:5]
    else:data[0]^=1
    target.write_bytes(data);dest=tmp_path/'output'
    with pytest.raises((ValueError,InvalidTag)):b.decrypt_to(target,dest,key)
    assert not dest.exists() and not list(tmp_path.glob('*.partial-*'))


def test_pg_dump_failure_does_not_leave_a_valid_archive(tmp_path,monkeypatch):
    monkeypatch.setattr(b.subprocess,'Popen',lambda *a,**kw:Process(b'incomplete',1))
    target=tmp_path/'backup'
    with pytest.raises(RuntimeError):b.backup('postgresql://localhost/cuota_test',target,os.urandom(32))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('url,operational',[
 ('postgresql://localhost/cuota',''),('sqlite:///cuota_test',''),
 ('postgresql://other-host/cuota_test','postgresql://localhost/cuota_test'),
 ('postgresql://localhost/postgres',''),
])
def test_database_test_gate_rejects_unsafe(url,operational):
    with pytest.raises(ValueError):validate_test_database(url,operational)


def test_database_gate_and_restore_require_distinct_explicit_targets():
    assert validate_test_database('postgresql://localhost/cuota_test','postgresql://localhost/cuota').database=='cuota_test'
    b.assert_safe_test_target('postgresql://localhost/isolated_restore','postgresql://localhost/cuota','isolated_restore')
    with pytest.raises(ValueError):b.assert_safe_test_target('postgresql://localhost/cuota_test','postgresql://different/cuota_test','cuota_test')
    with pytest.raises(ValueError):b.assert_safe_test_target('postgresql://localhost/cuota','', 'cuota')
    with pytest.raises(ValueError):b.assert_safe_test_target('postgresql://localhost/cuota_test','', 'YES')
