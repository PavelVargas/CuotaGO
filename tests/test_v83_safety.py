"""Framework-independent security, CSV and query-isolation regression checks."""
import ast
import base64
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS
from datetime import date, datetime, timedelta
from decimal import Decimal as D
import pytest
from sqlalchemy import select, event, func
from sqlalchemy.orm import with_loader_criteria, selectinload
from v83_harness import database, module
ROOT=Path(__file__).resolve().parents[1]

def direct(relative):
    p=ROOT/relative
    spec=importlib.util.spec_from_file_location('v83_direct_'+p.stem,p)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

@pytest.fixture
def x():
    ctx=database();yield ctx;ctx.s.close();ctx.engine.dispose()

@pytest.mark.parametrize('timestamp,expected',[(59,'94287082'),(1111111109,'07081804'),(1111111111,'14050471'),(1234567890,'89005924'),(2000000000,'69279037'),(20000000000,'65353130')])
def test_totp_rfc6238_sha1(timestamp,expected):
    m=direct('cuotago/security_primitives.py');secret=base64.b32encode(b'12345678901234567890').decode()
    assert m.totp(secret,timestamp//30,digits=8)==expected
    six=expected[-6:]
    assert m.verify_totp(secret,six,at=timestamp)==timestamp//30
    assert m.verify_totp(secret,six,at=timestamp,last_counter=timestamp//30) is None

@pytest.mark.parametrize('value',['https://elsewhere.test','//elsewhere.test','/%2felsewhere.test','/\\elsewhere.test','/%255celsewhere','/ok%0aLocation:elsewhere','javascript:alert(1)',None])
def test_redirects_reject_external_or_control(value):
    assert direct('cuotago/security_primitives.py').safe_next(value,'/safe')=='/safe'

def test_auth_secret_encryption_and_random_tokens():
    m=direct('cuotago/security_primitives.py');secret=m.new_totp_secret();key='private key from secret manager'
    encrypted=m.encrypt_secret(secret,key)
    assert secret not in encrypted and m.decrypt_secret(encrypted,key)==secret
    with pytest.raises(Exception):m.decrypt_secret(encrypted,key+'different')
    values={m.new_token() for _ in range(100)};assert len(values)==100 and all(len(v)==43 for v in values)
    assert m.safe_next('/reports?period=month')=='/reports?period=month'

def test_business_day_month_and_dst_boundaries():
    m=direct('cuotago/business_time.py')
    assert m.business_date(datetime(2026,11,1,1))==date(2026,10,31)
    first,last=m.utc_bounds(date(2026,10,31),date(2026,10,31));assert first==datetime(2026,10,31,4) and last==datetime(2026,11,1,4)
    first,last=m.utc_bounds(date(2026,3,8),date(2026,3,8),'America/New_York');assert last-first==timedelta(hours=23)

@pytest.mark.parametrize('frequency,expected', [('biweekly',date(2026,1,15)),('every15',date(2026,1,16)),('weekly',date(2026,1,8))])
def test_explicit_frequency(frequency,expected):
    m=direct('cuotago/schedules.py');assert list(m.due_dates(date(2026,1,1),frequency,2))[1]==expected

def test_monthly_keeps_anchor_and_semimonthly():
    m=direct('cuotago/schedules.py')
    assert list(m.due_dates(date(2026,1,31),'monthly',3))==[date(2026,1,31),date(2026,2,28),date(2026,3,31)]
    assert list(m.due_dates(date(2026,1,31),'semi_monthly',4))==[date(2026,1,31),date(2026,2,15),date(2026,2,28),date(2026,3,15)]
    with pytest.raises(ValueError):list(m.due_dates(date(2026,1,3),'semi_monthly',3))

def csv_bytes(kind,rows,api):
    import csv,io
    f=io.StringIO();writer=csv.DictWriter(f,fieldnames=api.COLUMNS[kind]);writer.writeheader();writer.writerows(rows);return f.getvalue().encode()

def client_row(key='1',document='DOC1'):
    return dict(external_id=key,full_name='Persona importada',document_id=document,phone='8095550100',email='person@example.test',address='Direccion')

def test_preview_confirm_replay_and_tenant_scope(x):
    api=module('operations.importing');payload=csv_bytes('clients',[client_row()],api)
    before=x.s.query(x.m.Client).count();batch,rows=api.preview_import(x.s,x.org.id,x.u.id,'clients',payload);x.s.commit()
    assert x.s.query(x.m.Client).count()==before
    with pytest.raises(LookupError):api.apply_import(x.s,x.other.id,x.v.id,batch.id,batch.digest,'America/Santo_Domingo')
    with pytest.raises(ValueError):api.apply_import(x.s,x.org.id,x.u.id,batch.id,'wrong','America/Santo_Domingo')
    api.apply_import(x.s,x.org.id,x.u.id,batch.id,batch.digest,'America/Santo_Domingo');x.s.commit()
    api.apply_import(x.s,x.org.id,x.u.id,batch.id,batch.digest,'America/Santo_Domingo');x.s.commit()
    assert x.s.query(x.m.Client).count()==before+1
    with pytest.raises(ValueError):api.preview_import(x.s,x.org.id,x.u.id,'clients',payload)

def test_import_expiry_actor_and_integrity(x):
    api=module('operations.importing');batch,rows=api.preview_import(x.s,x.org.id,x.u.id,'clients',csv_bytes('clients',[client_row()],api));x.s.commit()
    with pytest.raises(PermissionError):api.apply_import(x.s,x.org.id,x.v.id,batch.id,batch.digest,'America/Santo_Domingo')
    batch.expires_at=datetime(2000,1,1)
    with pytest.raises(ValueError):api.apply_import(x.s,x.org.id,x.u.id,batch.id,batch.digest,'America/Santo_Domingo')
    batch.expires_at=datetime(2999,1,1);batch.payload+=' '
    with pytest.raises(ValueError):api.apply_import(x.s,x.org.id,x.u.id,batch.id,batch.digest,'America/Santo_Domingo')

def test_opening_balances_do_not_create_cash_or_sale_stock(x):
    api=module('operations.importing');row=dict(external_id='opening1',client_id=x.c.id,description='Saldo inicial',total='1000',paid='100',balance='900',first_due='2026-11-01',count='7',frequency='monthly',cost='500')
    batch,_=api.preview_import(x.s,x.org.id,x.u.id,'balances',csv_bytes('balances',[row],api));x.s.commit()
    api.apply_import(x.s,x.org.id,x.u.id,batch.id,batch.digest,'America/Santo_Domingo');x.s.commit()
    c=x.s.query(x.m.Contract).one()
    assert c.principal_paid_total==100 and c.balance==900
    assert sum(i.amount for i in c.installments)==900
    assert c.asset.is_virtual and c.asset.available_quantity==0
    assert x.s.query(x.m.Payment).count()==x.s.query(x.n.MoneyEntry).count()==0

@pytest.mark.parametrize('mutator',[lambda row:row.update(total='NaN'),lambda row:row.update(paid='Infinity'),lambda row:row.update(balance='1'),lambda row:row.update(cost='2000'),lambda row:row.update(frequency='unknown')])
def test_opening_validation(mutator,x):
    api=module('operations.importing');row=dict(external_id='opening1',client_id=x.c.id,description='Saldo',total='1000',paid='100',balance='900',first_due='2026-11-01',count='7',frequency='monthly',cost='500');mutator(row)
    with pytest.raises(ValueError):api.parse_csv(csv_bytes('balances',[row],api),'balances')

def test_csv_duplicate_documents_and_limits(x):
    api=module('operations.importing')
    with pytest.raises(ValueError):api.parse_csv(csv_bytes('clients',[client_row(),client_row('2')],api),'clients')
    with pytest.raises(ValueError):api.parse_csv(b'\xff\xfe','clients')
    with pytest.raises(ValueError):api.parse_csv(b'x'*(1024*1024+1),'clients')

def test_bank_import_does_not_confirm_cash_and_match_once(x):
    api=module('operations.importing');at=datetime(2026,11,1,1)
    payload=csv_bytes('bank',[dict(external_id='tx1',date='2026-10-31',amount='120',reference='BANK1')],api)
    b,_=api.preview_import(x.s,x.org.id,x.u.id,'bank',payload,'Banco prueba');x.s.commit();api.apply_import(x.s,x.org.id,x.u.id,b.id,b.digest,'America/Santo_Domingo');x.s.commit()
    assert x.s.query(x.n.MoneyEntry).count()==0
    e=module('operations.cash').post_entry(x.s,x.org.id,x.u.id,'test',1,120,'transfer','Prueba',occurred_at=at);x.s.commit()
    line=x.s.query(x.n.BankLine).one();api.match_bank_line(x.s,x.org.id,x.u.id,line.id,e.id,'Referencia bancaria coincide','America/Santo_Domingo');x.s.commit()
    assert line.money_entry_id==e.id
    with pytest.raises(ValueError):api.match_bank_line(x.s,x.org.id,x.u.id,line.id,e.id,'Segunda vez','America/Santo_Domingo')

def test_collector_query_scope_with_same_asset_and_other_tenant(x):
    from test_v83_services import contract
    mine=contract(x);x.c.assigned_collector_id=x.u.id
    otherclient=x.m.Client(organization_id=x.org.id,full_name='No asignado');foreign=x.m.Client(organization_id=x.other.id,full_name='Otro negocio',assigned_collector_id=x.u.id)
    x.s.add_all([otherclient,foreign]);x.s.flush()
    another=x.m.Contract(organization_id=x.org.id,client_id=otherclient.id,asset_id=x.a.id,code='OTHER',deal_type='credit_sale',total_amount=100,base_amount=100,down_payment=0,installment_amount=100,quantity=1,frequency='monthly',start_date=date.today(),first_due_date=date.today(),status='active')
    x.s.add(another);x.s.add_all([x.m.Payment(contract=mine,amount=50,method='cash'),x.m.Payment(contract=another,amount=70,method='cash')]);x.s.commit();x.s.expunge_all()
    node=next(n for n in ast.parse((ROOT/'cuotago/request_guards.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='assigned_portfolio');node.decorator_list=[]
    scope=NS(collector_scope=(x.org.id,x.u.id))
    env=dict(g=scope,has_request_context=lambda:True,select=select,with_loader_criteria=with_loader_criteria)
    for name in ('Client','Contract','Payment','Installment','PaymentPromise','CollectionNote'):env[name]=getattr(x.m,name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'scope','exec'),env)
    fn=env['assigned_portfolio'];event.listen(x.s,'do_orm_execute',fn)
    try:
        assert [c.id for c in x.s.query(x.m.Client)]==[x.c.id]
        assert [c.id for c in x.s.query(x.m.Contract)]==[mine.id]
        assert x.s.query(func.sum(x.m.Payment.amount)).scalar()==50
        assert x.s.query(x.m.Contract.id).filter_by(id=another.id).first() is None
        # Stock must account for both agreements, not only the collector's account.
        a=x.s.query(x.m.Asset).options(selectinload(x.m.Asset.contracts)).execution_options(cuotago_full_stock=True).one()
        assert a.committed_quantity==2
    finally:event.remove(x.s,'do_orm_execute',fn)
