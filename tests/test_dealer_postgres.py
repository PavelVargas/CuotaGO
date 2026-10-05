"""Optional real HTTP/transaction races in an isolated PostgreSQL schema.

CUOTAGO_RUN_PG_TESTS=1 and TEST_DATABASE_URL must target a STAGING database.
No public tables are dropped. Each test owns a new randomly named schema.
This module is not a substitute for backing up or testing a deployment.
"""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from decimal import Decimal
from threading import Barrier

import pytest

if os.getenv('CUOTAGO_RUN_PG_TESTS') != '1':
    pytest.skip('Opt-in PostgreSQL races: set CUOTAGO_RUN_PG_TESTS=1 on staging only.', allow_module_level=True)
pytest.importorskip('flask')
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from cuotago import create_app
from cuotago.extensions import db
from cuotago.models import Asset, Client, Contract, Installment, Organization, Sale, User, Payment


@pytest.fixture
def app_data():
    dsn=os.getenv('TEST_DATABASE_URL')
    if not dsn:pytest.skip('A separate TEST_DATABASE_URL is required.')
    parsed=make_url(dsn)
    if parsed.get_backend_name()!='postgresql':pytest.fail('PostgreSQL required; SQLite cannot test FOR UPDATE.')
    if parsed.drivername=='postgresql': parsed=parsed.set(drivername='postgresql+psycopg')
    schema='cuotago_qa_'+uuid.uuid4().hex
    admin=create_engine(parsed)
    with admin.begin() as connection:connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        app=create_app({'TESTING':True,'WTF_CSRF_ENABLED':False,'SECRET_KEY':uuid.uuid4().hex,
            'SQLALCHEMY_DATABASE_URI':parsed,'AUTO_CREATE_DB':False,
            'SQLALCHEMY_ENGINE_OPTIONS':{'connect_args':{'options':f'-c search_path={schema} -c lock_timeout=8000 -c statement_timeout=20000'}},
            'PUSH_NOTIFICATIONS_ENABLED':False,'PUSH_SCHEDULER_ENABLED':False})
        with app.app_context():
            db.create_all()
            org=Organization(name='Isolated concurrency QA');db.session.add(org);db.session.flush()
            user=User(organization_id=org.id,name='QA Owner',email='owner@example.invalid',role='owner',password_hash='unused')
            person=Client(organization_id=org.id,full_name='QA Client')
            asset=Asset(organization_id=org.id,kind='car',name='QA stock',quantity_total=1,estimated_value=800,sale_price=1000,status='available')
            db.session.add_all([user,person,asset]);db.session.commit()
            data={'user':user.id,'client':person.id,'asset':asset.id,'org':org.id}
        yield app,data
    finally:
        if 'app' in locals():
            with app.app_context():db.session.remove();db.engine.dispose()
        with admin.begin() as connection:connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def race(app,user_id,requests):
    barrier=Barrier(len(requests),timeout=15)
    def run(item):
        endpoint,data=item
        with app.test_client() as client:
            with client.session_transaction() as session:
                session['_user_id']=str(user_id);session['_fresh']=True
            barrier.wait()
            response=client.post(endpoint,data=data,follow_redirects=False)
            assert response.status_code in {200,302,303}, (response.status_code,response.data[:200])
            return response.status_code
    with ThreadPoolExecutor(max_workers=len(requests)) as executor:
        return list(executor.map(run,requests))


def sale_data(data,key=None):
    return {'asset_id':data['asset'],'client_id':data['client'],'quantity':'1','unit_price':'1000',
            'payment_method':'cash','sale_date':date.today().isoformat(),'request_key':key or uuid.uuid4().hex}


def agreement_data(data):
    return {'asset_id':data['asset'],'client_id':data['client'],'quantity':'1','unit_price':'1000','profit_margin_percent':'0',
        'deal_type':'credit_sale','total_amount':'1000','down_payment':'0','installment_count':'2','installment_amount':'500',
        'daily_late_interest':'0','frequency':'monthly','start_date':date.today().isoformat(),
        'first_due_date':(date.today()+timedelta(days=30)).isoformat(),'request_key':uuid.uuid4().hex}


@pytest.mark.parametrize('same_key',[False,True])
def test_two_sales_cannot_sell_the_last_unit(app_data,same_key):
    app,d=app_data;key=uuid.uuid4().hex
    race(app,d['user'],[('/sales/new',sale_data(d,key)),('/sales/new',sale_data(d,key if same_key else None))])
    with app.app_context():
        assert Sale.query.count()==1
        assert db.session.get(Asset,d['asset']).available_quantity==0


def test_sale_and_agreement_share_the_stock_lock(app_data):
    app,d=app_data
    race(app,d['user'],[('/sales/new',sale_data(d)),('/contracts/new',agreement_data(d))])
    with app.app_context():
        assert Sale.query.count()+Contract.query.count()==1
        assert db.session.get(Asset,d['asset']).available_quantity==0


def test_two_payments_do_not_overcollect(app_data):
    app,d=app_data
    with app.app_context():
        c=Contract(organization_id=d['org'],client_id=d['client'],asset_id=d['asset'],quantity=1,code='QA-C-1',
            deal_type='credit_sale',status='active',total_amount=100,base_amount=100,down_payment=0,installment_amount=100,
            daily_late_interest=0,frequency='monthly',start_date=date.today(),first_due_date=date.today()+timedelta(days=30))
        c.installments.append(Installment(sequence=1,amount=100,paid_amount=0,due_date=c.first_due_date))
        db.session.add(c);db.session.commit();contract_id=c.id
    req=lambda: {'amount':'75','method':'cash','payment_kind':'payment','request_key':uuid.uuid4().hex}
    race(app,d['user'],[(f'/contracts/{contract_id}/pay',req()),(f'/contracts/{contract_id}/pay',req())])
    with app.app_context():
        c=db.session.get(Contract,contract_id)
        assert c.paid_total==Decimal('75') and c.balance==Decimal('25')
        assert Payment.query.filter_by(contract_id=contract_id).count()==1
