"""Real HTTP/PostgreSQL acceptance tests. Never substitute SQLite for this gate.
Run explicitly with CUOTAGO_RUN_PG_TESTS=1 and a distinct *_test database.
Every fixture uses a random schema; no public-table deletion.
"""
import os
import uuid
import pytest
if os.environ.get('CUOTAGO_RUN_PG_TESTS')!='1':
    pytest.skip('Explicit PostgreSQL opt-in required',allow_module_level=True)
pytest.importorskip('flask')
from test_dealer_postgres import app_data,agreement_data
from cuotago.extensions import db
from cuotago.models import Asset,Contract,Payment,Supplier,User
from cuotago.operations.models import PurchaseOrder,MoneyEntry,PaymentReversal,CashShift,UserSession


def login(app):
    client=app.test_client()
    response=client.post('/login',data={'email':'owner@example.invalid','password':'QA-owner-password-83'})
    assert response.status_code in (302,303)
    return client


def post(client,path,data=None,key=None):
    return client.post(path,data=dict(data or {},request_key=key or uuid.uuid4().hex),follow_redirects=False)


@pytest.mark.parametrize('path',['/','/reports','/settings','/operations/','/operations/cash','/operations/orders','/operations/orders/new','/operations/imports','/operations/bank','/operations/collectors','/operations/controls','/operations/readiness','/security/'])
def test_pages_render_with_authenticated_session(app_data,path):
    app,d=app_data;client=login(app);r=client.get(path)
    assert r.status_code==200, (path,r.status_code,r.data[:200])


def test_purchase_receipt_retries_do_not_duplicate_stock(app_data):
    app,d=app_data;client=login(app)
    with app.app_context():
        supplier=Supplier(organization_id=d['org'],name='QA proveedor');db.session.add(supplier);db.session.commit();sid=supplier.id
    key=uuid.uuid4().hex;payload={'supplier_id':sid,'line_asset_id':str(d['asset']),'line_name':'','line_kind':'car','line_quantity':'3','line_unit_cost':'900'}
    assert post(client,'/operations/orders/new',payload,key).status_code==303
    assert post(client,'/operations/orders/new',payload,key).status_code==303
    with app.app_context():
        order=PurchaseOrder.query.one();oid=order.id;line=order.lines[0].id
        assert db.session.get(Asset,d['asset']).quantity_total==1
    key=uuid.uuid4().hex
    for _ in range(2):assert post(client,f'/operations/orders/{oid}/receive',{'qty_'+str(line):'1'},key).status_code==302
    with app.app_context():
        assert db.session.get(Asset,d['asset']).quantity_total==2
        assert db.session.get(PurchaseOrder,oid).lines[0].received==1


def test_payment_reversal_receipt_and_cash_rollback(app_data):
    app,d=app_data;client=login(app)
    assert post(client,'/operations/cash/open',{'opening':'100'}).status_code==302
    assert post(client,'/contracts/new',agreement_data(d)).status_code==302
    with app.app_context():cid=Contract.query.one().id
    assert post(client,f'/contracts/{cid}/pay',{'amount':'250','method':'cash','payment_kind':'payment'}).status_code==302
    with app.app_context():pid=Payment.query.one().id
    key=uuid.uuid4().hex
    assert post(client,f'/operations/payments/{pid}/reverse',{'reason':'Error de registro QA'},key).status_code==302
    assert post(client,f'/operations/payments/{pid}/reverse',{'reason':'Error de registro QA'},key).status_code==302
    with app.app_context():
        assert PaymentReversal.query.count()==1
        assert db.session.get(Payment,pid).voided_at is not None
        assert db.session.get(Contract,cid).paid_total==0
        assert sum(e.amount for e in MoneyEntry.query.all())==0
        shift=CashShift.query.one().id
    assert post(client,f'/operations/cash/{shift}/close',{'counted':'100','note':''}).status_code==302
    assert client.get(f'/payments/{pid}/receipt').status_code==200


def test_server_rejects_forged_id_and_missing_csrf(app_data):
    app,d=app_data;client=login(app)
    assert client.get('/operations/orders/999999').status_code==404
    app.config['WTF_CSRF_ENABLED']=True
    assert post(client,'/operations/cash/open',{'opening':'100'}).status_code==400
    with app.app_context():assert CashShift.query.count()==0


def test_revoked_session_loses_access(app_data):
    app,d=app_data;client=login(app)
    with app.app_context():
        from cuotago.business_time import utcnow
        record=UserSession.query.one();record.revoked_at=utcnow();db.session.commit()
    result=client.get('/operations/cash')
    assert result.status_code in (302,303,401)
