"""Performance regressions with real SQLAlchemy queries and isolated fixtures.

No customer data, network, Flask server, or production database is required.
PostgreSQL locking semantics are deliberately not inferred from SQLite tests.
"""
import ast
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import (Column, Date, DateTime, ForeignKey, Integer, LargeBinary,
                        Numeric, String, case, create_engine, event, func)
from sqlalchemy.orm import Session, Query, declarative_base, deferred, undefer
from test_dealer_workflows import functions

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 6)


def fee_context(current='60', *, paid=False, rate='10', status='active', activation=None,
                due=None, principal_paid_at=None, principal_paid=False, base='0'):
    item = NS(due_date=due or TODAY-timedelta(days=6), is_paid=paid,
              principal_paid_at=principal_paid_at, paid_at=None,
              principal_is_paid=principal_paid, late_fee_base_amount=D(base), late_fee_amount=D(current))
    contract = NS(id=1, installments=[item], status=status, daily_late_interest=D(rate),
                  late_fee_started_on=activation, start_date=TODAY-timedelta(days=40))
    return contract, item


def fee_env(lock):
    commits = []
    env = functions('cuotago/main.py', ['_late_fee_updates', 'sync_contract_late_fees'], dict(
        money_decimal=lambda x: D(str(x or 0)).quantize(D('.01')), local_today=lambda: TODAY,
        lock_contract=lock, db=NS(session=NS(commit=lambda: commits.append(True))),
    ))
    return env['sync_contract_late_fees'], commits


@pytest.mark.parametrize('current,paid,rate,status', [
    ('60',False,'10','active'), ('90',False,'10','active'), ('0',True,'10','active'),
    ('0',False,'0','active'), ('0',False,'10','completed'), ('0',False,'10','cancelled'),
])
def test_current_or_ineligible_fee_never_locks_stock(current, paid, rate, status):
    c, i = fee_context(current, paid=paid, rate=rate, status=status)
    def forbidden(_): raise AssertionError('Unnecessary write lock')
    sync, commits = fee_env(forbidden)
    assert sync(c, commit=True) is False
    assert i.late_fee_amount == D(current) and commits == []


@pytest.mark.parametrize('activation,paid_at,expected', [
    (None,None,'60'), (TODAY-timedelta(days=2),None,'20'), (TODAY,None,'0'),
    (None,datetime(2026,10,3),'30'), (TODAY-timedelta(days=2),datetime(2026,10,3),'0'),
])
def test_original_fee_dates_and_payment_stop_are_preserved(activation, paid_at, expected):
    c,i = fee_context('0',activation=activation,principal_paid_at=paid_at)
    calls=[]
    sync, commits=fee_env(lambda id: (calls.append(id) or c))
    assert sync(c,commit=True) is (D(expected)>0)
    assert i.late_fee_amount==D(expected)
    assert calls == ([1] if D(expected)>0 else [])
    assert len(commits)==len(calls)


def test_write_recomputes_after_another_payment_while_waiting():
    stale,_=fee_context('0')
    fresh,item=fee_context('60',paid=True)
    sync,commits=fee_env(lambda _: fresh)
    assert sync(stale,commit=True) is False
    assert item.late_fee_amount==D('60') and not commits


def test_existing_write_lock_is_reused_and_no_commit_without_permission():
    c,i=fee_context('0',base='7')
    sync,commits=fee_env(lambda _: pytest.fail('already locked'))
    assert sync(c,already_locked=True,commit=False) is True
    assert i.late_fee_amount==D('67') and not commits


def test_second_daily_visit_does_not_repeat_lock():
    c,i=fee_context('0'); calls=[]
    sync,commits=fee_env(lambda id: (calls.append(id) or c))
    assert sync(c,commit=True)
    for _ in range(100): assert not sync(c,commit=True)
    assert calls==[1] and commits==[True]


class TestQuery(Query):
    __test__ = False
    def first_or_404(self):
        item = self.first()
        if item is None: raise LookupError(404)
        return item


@pytest.fixture
def orm():
    Base = declarative_base()
    class Contract(Base):
        __tablename__='contracts'
        id=Column(Integer,primary_key=True);organization_id=Column(Integer);status=Column(String)
    class Installment(Base):
        __tablename__='installments'
        id=Column(Integer,primary_key=True);contract_id=Column(Integer,ForeignKey('contracts.id'));due_date=Column(Date)
        amount=Column(Numeric(12,2));paid_amount=Column(Numeric(12,2));late_fee_amount=Column(Numeric(12,2));late_fee_paid=Column(Numeric(12,2))
    class Promise(Base):
        __tablename__='promises'
        id=Column(Integer,primary_key=True);organization_id=Column(Integer);status=Column(String);promised_date=Column(Date)
    class Asset(Base):
        __tablename__='assets'
        id=Column(Integer,primary_key=True);organization_id=Column(Integer);image_mime=Column(String);image_updated_at=Column(DateTime)
        image_data=deferred(Column(LargeBinary));image_thumb_data=deferred(Column(LargeBinary))
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine, query_cls=TestQuery) as session:
        for cls in [Contract, Installment, Promise, Asset]: cls.query=session.query(cls)
        session.add_all([Contract(id=1,organization_id=1,status='active'),Contract(id=2,organization_id=2,status='active'),
                         Contract(id=3,organization_id=1,status='completed')])
        session.commit()
        statements=[]
        event.listen(engine,'before_cursor_execute', lambda conn,cursor,stmt,*args:statements.append(stmt))
        yield NS(session=session,Contract=Contract,Installment=Installment,Promise=Promise,Asset=Asset,statements=statements)
    engine.dispose()


def summary_env(x):
    # SQLite max(a,b) stands in for PostgreSQL greatest(a,b); identical fixtures.
    I=x.Installment
    remaining=lambda:func.max(I.amount-I.paid_amount,0)+func.max(I.late_fee_amount-I.late_fee_paid,0)
    return functions('cuotago/main.py',['payment_notification_summary'],dict(
        db=NS(session=x.session),Contract=x.Contract,Installment=I,PaymentPromise=x.Promise,
        installment_remaining_sql=remaining,current_user=NS(organization_id=1),local_today=lambda:TODAY,
        timedelta=timedelta,Decimal=D,func=func,case=case))['payment_notification_summary']


def add_installment(x, days, *, contract=1, paid=0, fee=0):
    x.session.add(x.Installment(contract_id=contract,due_date=TODAY+timedelta(days=days),
        amount=D('100'),paid_amount=D(paid),late_fee_amount=D(fee),late_fee_paid=0))


def test_badge_uses_two_aggregate_queries_with_no_history_or_write_locks(orm):
    x=orm
    for d in [-1,0,3]:add_installment(x,d)
    add_installment(x,-2,paid=100)  # Fully paid: not an alert.
    add_installment(x,-2,paid=100,fee=10)  # Unpaid fee: still an alert.
    add_installment(x,8);add_installment(x,0,contract=2);add_installment(x,0,contract=3)
    x.session.add_all([x.Promise(organization_id=1,status='pending',promised_date=TODAY),
        x.Promise(organization_id=1,status='broken',promised_date=TODAY-timedelta(days=1)),
        x.Promise(organization_id=1,status='kept',promised_date=TODAY),
        x.Promise(organization_id=2,status='pending',promised_date=TODAY),
        x.Promise(organization_id=1,status='pending',promised_date=TODAY+timedelta(days=8))])
    x.session.commit();x.session.expunge_all();x.statements.clear()
    assert summary_env(x)()=={'ok':True,'count':4,'promiseCount':2,'badgeCount':6,'urgentCount':3}
    assert len(x.statements)==2
    assert not x.session.identity_map
    assert all(q.startswith('SELECT') and 'FOR UPDATE' not in q for q in x.statements)


def test_badge_matches_existing_500_item_center_limit(orm):
    x=orm
    for _ in range(510):add_installment(x,0)
    x.session.commit();x.statements.clear()
    data=summary_env(x)()
    assert data['count']==data['urgentCount']==500
    assert len(x.statements)==2 and 'items' not in data


class FakeResponse:
    def __init__(self, payload, mimetype):self.data=payload;self.mimetype=mimetype;self.headers={}
    def set_etag(self, tag):self.tag=tag
    def make_conditional(self, request):return self


def image_env(x, *, thumb=True, org=1):
    def abort(code):raise LookupError(code)
    return functions('cuotago/main.py',['asset_image'],dict(
        Asset=x.Asset,undefer=undefer,current_user=NS(organization_id=org),
        request=NS(args={'thumb':'1' if thumb else '0','v':'test'}),abort=abort,Response=FakeResponse))['asset_image']


def test_thumbnail_never_reads_full_original_blob(orm):
    x=orm
    x.session.add(x.Asset(id=1,organization_id=1,image_mime='image/webp',image_updated_at=datetime(2026,10,6),
        image_data=b'original'*150000,image_thumb_data=b'small-webp'))
    x.session.commit();x.session.expunge_all();x.statements.clear()
    result=image_env(x)(1)
    assert result.data==b'small-webp' and result.mimetype=='image/webp'
    assert len(x.statements)==1
    assert 'assets.image_data ' not in x.statements[0] and 'assets.image_thumb_data' in x.statements[0]
    assert result.headers['Cache-Control'].startswith('private,')
    with pytest.raises(LookupError):image_env(x,org=2)(1)


def test_detail_image_reads_original_not_thumbnail(orm):
    x=orm
    x.session.add(x.Asset(id=1,organization_id=1,image_mime='image/jpeg',image_updated_at=None,
                         image_data=b'original-jpeg',image_thumb_data=b'thumb'))
    x.session.commit();x.session.expunge_all();x.statements.clear()
    result=image_env(x,thumb=False)(1)
    assert result.data==b'original-jpeg' and result.mimetype=='image/jpeg'
    assert len(x.statements)==1 and 'assets.image_thumb_data' not in x.statements[0]


def test_public_asset_gate_returns_before_resolving_current_user():
    tree=ast.parse((ROOT/'cuotago/__init__.py').read_text())
    node=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='enforce_account_and_subscription_state')
    node.decorator_list=[]
    class UserNotToBeLoaded:
        @property
        def is_authenticated(self):raise RuntimeError('user lookup')
    req=NS(endpoint='static')
    env=dict(request=req,current_user=UserNotToBeLoaded())
    exec(compile(ast.Module(body=[node],type_ignores=[]),'gate','exec'),env)
    for name in ['static','service_worker','healthz','offline']:
        req.endpoint=name
        assert env[node.name]() is None
    for name in ['main.asset_image','main.notifications_api','main.sale_new']:
        req.endpoint=name
        with pytest.raises(RuntimeError, match='user lookup'):env[node.name]()


def test_summary_and_private_images_keep_auth_and_permission_decorators():
    tree=ast.parse((ROOT/'cuotago/main.py').read_text())
    for name,permission in [('notifications_api','collections.view'),('asset_image','inventory.view')]:
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
        dec=' '.join(ast.unparse(n) for n in node.decorator_list)
        assert 'login_required' in dec and permission in dec


def test_no_context_processor_badge_query_and_no_parse_blocking_motion():
    src=(ROOT/'cuotago/main.py').read_text()
    code=src.split('def inject_helpers():',1)[1].split('@main_bp.get',1)[0]
    assert 'urgent_payment_alert_count()' not in code
    base=(ROOT/'cuotago/templates/base.html').read_text()
    assert 'defer' in base.split("filename='js/motion.js'",1)[1].split('</script>',1)[0]
    app=(ROOT/'cuotago/static/js/app.js').read_text()
    pull=app.split('const setupPullToRefresh =',1)[1].split('const setupAssetPhotoPreview',1)[0]
    assert 'passive: false' not in pull and '.preventDefault()' not in pull
    assert 'inNestedScroller' in pull
    watcher=app.split('const startPaymentAlertWatcher =',1)[1].split('const buildNotificationOptions',1)[0]
    assert 'summary: true' in watcher and 'setInterval(' not in watcher
    assert 'visibilitychange' in watcher and 'pagehide' in watcher and 'request.abort()' in watcher


def test_full_photos_not_loaded_for_sales_catalog():
    js=(ROOT/'cuotago/static/js/sales.js').read_text()
    cards=js.split('const renderItems =',1)[1].split('const load =',1)[0]
    assert 'srcset =' not in cards and 'setPhoto(image, item)' in cards
    tpl=(ROOT/'cuotago/templates/sales/_components.html').read_text()
    assert 'srcset=' not in tpl and 'thumb=1' in tpl


def test_offline_shell_has_no_user_or_application_polling():
    html=(ROOT/'cuotago/templates/offline.html').read_text()
    assert 'extends' not in html and 'current_user' not in html
    assert 'js/app.js' not in html and 'csrf_token' not in html
    assert 'location.reload()' in html
