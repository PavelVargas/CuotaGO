"""Lock query shape and identity-map refresh tests. SQLite does not test locking.
The PostgreSQL route races live in test_dealer_postgres.py and are opt-in.
"""
from types import SimpleNamespace as NS
import pytest
from sqlalchemy import Column, ForeignKey, Integer, String, create_engine, event, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, declarative_base, relationship, selectinload
from test_dealer_workflows import functions


@pytest.fixture
def models():
    Base=declarative_base()
    class Asset(Base):
        __tablename__='assets'
        id=Column(Integer,primary_key=True);organization_id=Column(Integer);status=Column(String)
        contracts=relationship('Contract');sales=relationship('Sale');investments=relationship('Investment')
    class Contract(Base):
        __tablename__='contracts'
        id=Column(Integer,primary_key=True);organization_id=Column(Integer);asset_id=Column(Integer,ForeignKey('assets.id'))
        installments=relationship('Installment');payments=relationship('Payment');payment_promises=relationship('Promise')
    class Sale(Base):
        __tablename__='sales'
        id=Column(Integer,primary_key=True);organization_id=Column(Integer);asset_id=Column(Integer,ForeignKey('assets.id'))
    class Investment(Base):
        __tablename__='investments'
        id=Column(Integer,primary_key=True);asset_id=Column(Integer,ForeignKey('assets.id'))
    class Installment(Base):
        __tablename__='installments'
        id=Column(Integer,primary_key=True);contract_id=Column(Integer,ForeignKey('contracts.id'))
    class Payment(Base):
        __tablename__='payments'
        id=Column(Integer,primary_key=True);contract_id=Column(Integer,ForeignKey('contracts.id'))
    class Promise(Base):
        __tablename__='promises'
        id=Column(Integer,primary_key=True);contract_id=Column(Integer,ForeignKey('contracts.id'))
    engine=create_engine('sqlite:///:memory:');Base.metadata.create_all(engine)
    with Session(engine,expire_on_commit=False) as session:
        for model in [Asset,Contract,Sale]:model.query=session.query(model)
        session.add_all([Asset(id=1,organization_id=1,status='available'),Asset(id=2,organization_id=2),
            Contract(id=1,organization_id=1,asset_id=1),Sale(id=1,organization_id=1,asset_id=1),
            Contract(id=2,organization_id=2,asset_id=2),Sale(id=2,organization_id=2,asset_id=2)])
        session.commit();captured=[]
        def record(state):
            if getattr(state.statement,'_for_update_arg',None) is not None:
                captured.append(str(state.statement.compile(dialect=postgresql.dialect())))
        event.listen(session,'do_orm_execute',record)
        def abort(code):raise PermissionError(code)
        env=functions('cuotago/transactions.py',['lock_asset','lock_contract','lock_sale'],dict(
            Asset=Asset,Contract=Contract,Sale=Sale,db=NS(session=session),current_user=NS(organization_id=1),selectinload=selectinload,abort=abort))
        yield NS(env=env,session=session,Asset=Asset,captured=captured)
    engine.dispose()


@pytest.mark.parametrize('function,table',[('lock_contract','contracts'),('lock_sale','sales')])
def test_locks_stock_before_operation_without_nullable_join(models,function,table):
    x=models;result=x.env[function](1)
    assert result.id==1
    assert len(x.captured)==2
    assert 'FOR UPDATE OF assets' in x.captured[0]
    assert 'FOR UPDATE OF '+table in x.captured[1]
    assert all('LEFT OUTER JOIN' not in q for q in x.captured)


def test_waiter_reload_replaces_cached_asset_state(models):
    x=models;asset=x.session.get(x.Asset,1);assert asset.status=='available'
    x.session.execute(update(x.Asset).where(x.Asset.id==1).values(status='sold'),execution_options={'synchronize_session':False})
    assert asset.status=='available'
    result=x.env['lock_asset'](1)
    assert result is asset and result.status=='sold'


@pytest.mark.parametrize('function',['lock_asset','lock_contract','lock_sale'])
def test_lock_queries_do_not_access_other_tenant(models,function):
    with pytest.raises(PermissionError) as error:models.env[function](2)
    assert error.value.args==(404,)


def test_optional_missing_stock_returns_none(models):
    assert models.env['lock_asset'](2,required=False) is None
