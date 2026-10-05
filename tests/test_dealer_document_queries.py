"""Execute the production document-index query against isolated SQLAlchemy data."""
from datetime import datetime
from types import SimpleNamespace as NS
import pytest
from sqlalchemy import Column,ForeignKey,Integer,String,Numeric,DateTime,create_engine,or_
from sqlalchemy.orm import Session,Query,declarative_base,relationship,joinedload
from test_dealer_workflows import functions
from dealer_fixtures import route_url

class Values(dict):
    def get(self,key,default=None,type=None):
        value=super().get(key,default)
        try:return type(value) if type else value
        except (TypeError,ValueError):return default

class PageQuery(Query):
    def paginate(self,*,page,per_page,error_out):
        total=self.count();pages=(total+per_page-1)//per_page
        return NS(items=self.offset((page-1)*per_page).limit(per_page).all(),total=total,pages=pages,
                  page=page,prev_num=page-1,next_num=page+1,has_prev=page>1,has_next=page<pages)

@pytest.fixture
def documents():
    Base=declarative_base()
    class Asset(Base):
        __tablename__='assets'
        id=Column(Integer,primary_key=True);organization_id=Column(Integer);name=Column(String);identifier=Column(String)
    class Client(Base):
        __tablename__='clients'
        id=Column(Integer,primary_key=True);organization_id=Column(Integer);full_name=Column(String);phone=Column(String);document_id=Column(String)
    class Sale(Base):
        __tablename__='sales'
        id=Column(Integer,primary_key=True);organization_id=Column(Integer);asset_id=Column(Integer,ForeignKey('assets.id'));client_id=Column(Integer,ForeignKey('clients.id'))
        code=Column(String);buyer_name=Column(String);sale_date=Column(DateTime);status=Column(String);total_amount=Column(Numeric(12,2))
        client=relationship(Client);asset=relationship(Asset)
        @property
        def buyer_display(self):return self.client.full_name if self.client else self.buyer_name
    class Contract(Base):
        __tablename__='contracts'
        id=Column(Integer,primary_key=True);organization_id=Column(Integer);asset_id=Column(Integer,ForeignKey('assets.id'));client_id=Column(Integer,ForeignKey('clients.id'));code=Column(String)
        asset=relationship(Asset);client=relationship(Client)
    class Payment(Base):
        __tablename__='payments'
        id=Column(Integer,primary_key=True);contract_id=Column(Integer,ForeignKey('contracts.id'));receipt_code=Column(String);amount=Column(Numeric(12,2));paid_at=Column(DateTime)
        contract=relationship(Contract)
    engine=create_engine('sqlite:///:memory:');Base.metadata.create_all(engine)
    with Session(engine,query_cls=PageQuery) as session:
        for model in [Asset,Client,Sale,Contract,Payment]:model.query=session.query(model)
        now=datetime(2026,10,5)
        for tenant in [1,2]:
            session.add_all([Asset(id=tenant,organization_id=tenant,name='Carro '+str(tenant),identifier='PLACA-'+str(tenant)),
                Client(id=tenant,organization_id=tenant,full_name='Cliente '+str(tenant)),
                Sale(id=tenant,organization_id=tenant,asset_id=tenant,client_id=tenant,code='VENTA-'+str(tenant),buyer_name='',sale_date=now,status='completed',total_amount=100),
                Contract(id=tenant,organization_id=tenant,asset_id=tenant,client_id=tenant,code='ACUERDO-'+str(tenant)),
                Payment(id=tenant,contract_id=tenant,receipt_code='RECIBO-'+str(tenant),paid_at=now,amount=30)])
        session.commit()
        def abort(code):raise PermissionError(code)
        def scoped(model,id):
            item=model.query.filter_by(id=id,organization_id=1).first()
            if not item:abort(404)
            return item
        env=functions('cuotago/main.py',['documents'],dict(
            Sale=Sale,Asset=Asset,Client=Client,Contract=Contract,Payment=Payment,
            request=NS(args=Values()),current_user=NS(organization_id=1),has_permission=lambda u,p:True,
            joinedload=joinedload,or_=or_,url_for=route_url,contextual_url=route_url,
            render_template=lambda template,**kw:kw,abort=abort,
            scoped_asset=lambda id:scoped(Asset,id),scoped_client=lambda id:scoped(Client,id)))
        yield env
    engine.dispose()

@pytest.mark.parametrize('tab,title',[('sales','VENTA-1'),('payments','RECIBO-1'),('statements','Cliente 1')])
def test_document_tabs_are_tenant_scoped(documents,tab,title):
    documents['request'].args=Values(tab=tab)
    result=documents['documents']()
    assert [r['title'] for r in result['rows']]==[title]

@pytest.mark.parametrize('tab,q',[('sales','Cliente 1'),('payments','Carro 1'),('sales','PLACA-1')])
def test_registered_names_and_vehicle_search(documents,tab,q):
    documents['request'].args=Values(tab=tab,q=q)
    assert len(documents['documents']()['rows'])==1


def test_document_filter_cannot_switch_tenant(documents):
    documents['request'].args=Values(tab='sales',asset_id='2')
    with pytest.raises(PermissionError):documents['documents']()


def test_collector_does_not_receive_sales(documents):
    documents['has_permission']=lambda u,p:p in {'clients.view','payments.view'}
    documents['request'].args=Values(tab='sales')
    result=documents['documents']()
    assert result['tab']=='payments'
    assert [r['title'] for r in result['rows']]==['RECIBO-1']
