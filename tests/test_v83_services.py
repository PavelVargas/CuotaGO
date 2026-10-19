from datetime import date,datetime,timedelta
from decimal import Decimal as D
import json
import pytest
from sqlalchemy import select
from v83_harness import database,module

@pytest.fixture
def x():
    x=database();yield x;x.s.close();x.engine.dispose()

def contract(x,amount='900',paid='0'):
    c=x.m.Contract(organization_id=x.org.id,client_id=x.c.id,asset_id=x.a.id,code='TEST-001',deal_type='credit_sale',
        total_amount=D(amount),base_amount=100,down_payment=0,installment_amount=300,quantity=1,
        frequency='monthly',start_date=date(2026,10,1),first_due_date=date(2026,11,1),status='active',opening_paid=D(paid))
    x.s.add(c);x.s.flush();return c

def test_models_foreign_keys_created(x):
    assert len(x.db.Model.metadata.tables)>=35

def test_inventory_replenish_and_return(x):
    sale=x.m.Sale(organization_id=x.org.id,asset_id=x.a.id,quantity=9,unit_price=200,unit_cost=100,total_amount=1800,status='completed',sale_date=date.today(),code='SALE',payment_method='cash')
    x.s.add(sale);x.s.flush();x.s.expire(x.a,['sales'])
    api=module('money_ops');assert api.valued_quantity(x.a)==1
    api.receive_stock(x.a,10,200);assert x.a.estimated_value==D('190.91')
    api.return_stock_cost(x.a,9,100);sale.status='voided';x.s.flush()
    assert x.a.available_quantity==20
    assert x.a.estimated_value==D('150.00')

def test_order_partial_pay_advance_and_receipt(x):
    p=module('operations.purchasing')
    o=p.create_order(x.s,x.org.id,x.u.id,x.supplier.id,[dict(asset_id=x.a.id,quantity=3,unit_cost=150)])
    assert x.a.quantity_total==10
    x.s.commit()
    p.receive_order(x.s,x.org.id,x.u.id,o.id,{str(o.lines[0].id):1},'America/Santo_Domingo')
    assert x.a.quantity_total==11 and o.state=='partial'
    pay=p.pay_supplier(x.s,x.org.id,x.u.id,o.id,250,'transfer')
    assert p.order_totals(o)['advance']==D('100.00')
    with pytest.raises(ValueError):p.cancel_order(x.s,x.org.id,x.u.id,o.id,'Cancelar saldo pendiente')
    p.receive_order(x.s,x.org.id,x.u.id,o.id,{str(o.lines[0].id):2},'America/Santo_Domingo')
    assert o.state=='received' and p.order_totals(o)['payable']==D('200.00')
    assert x.a.quantity_total==13
    p.void_supplier_payment(x.s,x.org.id,x.u.id,pay.id,'Registro equivocado')
    x.s.flush();assert p.order_totals(o)['paid']==0
    assert sum(e.amount for e in x.s.query(x.n.MoneyEntry))==0

def test_order_overreceiving_fails_without_changes(x):
    p=module('operations.purchasing');o=p.create_order(x.s,x.org.id,x.u.id,x.supplier.id,[dict(asset_id=x.a.id,quantity=1,unit_cost=100)])
    x.s.commit()
    with pytest.raises(ValueError):p.receive_order(x.s,x.org.id,x.u.id,o.id,{str(o.lines[0].id):2},'America/Santo_Domingo')
    x.s.rollback();assert x.a.quantity_total==10

def test_order_new_asset_partial_twice(x):
    p=module('operations.purchasing');o=p.create_order(x.s,x.org.id,x.u.id,x.supplier.id,[dict(name='Nuevo producto',kind='phone',quantity=2,unit_cost=100)])
    x.s.commit();p.receive_order(x.s,x.org.id,x.u.id,o.id,{str(o.lines[0].id):1},'America/Santo_Domingo');x.s.commit()
    aid=o.lines[0].asset_id;p.receive_order(x.s,x.org.id,x.u.id,o.id,{str(o.lines[0].id):1},'America/Santo_Domingo');x.s.flush()
    assert x.s.get(x.m.Asset,aid).quantity_total==2

def test_purchase_idempotency_and_payload_mismatch(x):
    f=module('operations.common').operation
    op,replay=f(x.s,x.org.id,'purchase','a'*32,{'x':1});assert not replay
    op.result_id='12';x.s.commit()
    same,replay=f(x.s,x.org.id,'purchase','a'*32,{'x':1});assert same.id==op.id and replay
    with pytest.raises(ValueError):f(x.s,x.org.id,'purchase','a'*32,{'x':2})

def test_cash_open_record_close_freeze(x):
    c=module('operations.cash');shift=c.open_shift(x.s,x.org.id,x.u.id,100)
    c.post_entry(x.s,x.org.id,x.u.id,'test',1,50,'cash','Test')
    c.post_entry(x.s,x.org.id,x.u.id,'test',2,1000,'transfer','Transferencia')
    assert c.expected_cash(x.s,shift)==150
    with pytest.raises(ValueError):c.close_shift(x.s,x.org.id,x.u.id,shift.id,149,'')
    c.close_shift(x.s,x.org.id,x.u.id,shift.id,149,'Falta un peso');x.s.commit()
    assert shift.difference==D('-1.00')
    with pytest.raises(ValueError):c.close_shift(x.s,x.org.id,x.u.id,shift.id,150,'Otra vez')

def test_cash_required_atomic_rollback(x):
    x.s.add(x.n.OrganizationControls(organization_id=x.org.id,require_cash_shift=True));x.s.commit()
    with pytest.raises(ValueError):module('operations.cash').post_entry(x.s,x.org.id,x.u.id,'test',1,50,'cash','Test')
    x.s.rollback();assert x.s.query(x.n.MoneyEntry).count()==0

def test_reversal_allocated_payment_reopens_principal_and_fee(x):
    c=contract(x,amount='100')
    i=x.m.Installment(contract=c,sequence=1,due_date=date(2026,10,1),amount=100,paid_amount=0,late_fee_amount=10,late_fee_paid=0)
    x.s.add(i);x.s.flush();p=module('operations.payments');before=p.allocation_snapshot(c)
    i.paid_amount=100;i.late_fee_paid=10;i.paid_at=datetime(2026,10,2);i.principal_paid_at=i.paid_at
    pay=x.m.Payment(contract=c,amount=110,late_fee_amount=10,method='cash',receipt_code='CG1')
    x.s.add(pay);x.s.flush();p.save_allocations(x.s,c,pay,before);c.status='completed';x.s.commit()
    result=p.reverse_payment(x.s,x.org.id,x.u.id,c,pay.id,'Se registro dos veces','America/Santo_Domingo');x.s.flush()
    assert pay.voided_at and c.principal_balance==100 and i.remaining==110 and c.status=='active'
    assert result.amount==110 and x.s.query(x.n.PaymentReversal).count()==1
    with pytest.raises(ValueError):p.reverse_payment(x.s,x.org.id,x.u.id,c,pay.id,'Otro motivo','America/Santo_Domingo')

def test_reversal_legacy_has_explicit_correction(x):
    c=contract(x,amount='100');i=x.m.Installment(contract=c,sequence=1,due_date=date(2026,10,1),amount=100,paid_amount=100,late_fee_amount=0,late_fee_paid=0)
    pay=x.m.Payment(contract=c,amount=100,late_fee_amount=0,method='transfer',receipt_code='OLD')
    x.s.add_all([i,pay]);x.s.commit()
    rev=module('operations.payments').reverse_payment(x.s,x.org.id,x.u.id,c,pay.id,'Pago antiguo equivocado','America/Santo_Domingo')
    assert json.loads(rev.detail)['correction_installment'] is not None
    assert len(c.installments)==2 and c.principal_balance==100
    assert sum(z.principal_remaining for z in c.installments)==100

def test_reversal_tenant_scope(x):
    c=contract(x)
    with pytest.raises(LookupError):module('operations.payments').reverse_payment(x.s,x.other.id,x.v.id,c,1,'Intento cruzado','America/Santo_Domingo')

def test_payment_event_timezone_and_later_reversal(x):
    c=contract(x);p=x.m.Payment(contract=c,amount=50,late_fee_amount=0,method='cash',receipt_code='EVT',paid_at=datetime(2026,11,1,1))
    x.s.add(p);x.s.flush();x.s.add(x.n.PaymentReversal(organization_id=x.org.id,contract_id=c.id,payment_id=p.id,amount=50,late_fee_amount=0,reason='Error de registro',actor_id=x.u.id,reversed_at=datetime(2026,11,2,14),code='REV',detail='{}'))
    x.s.flush();r=module('reporting_v83');ids=select(x.m.Contract.id).where(x.m.Contract.organization_id==x.org.id)
    oct=r.payment_summary(x.s,ids,date(2026,10,31),date(2026,10,31),'America/Santo_Domingo')
    assert oct['total']==50 and oct['daily'][date(2026,10,31)]==50
    nov=r.payment_summary(x.s,ids,date(2026,11,2),date(2026,11,2),'America/Santo_Domingo')
    assert nov['total']==-50 and nov['reversed_count']==1

def test_sql_aggregate_matches_model(x):
    c=contract(x);x.s.add_all([x.m.Payment(contract=c,amount=90,late_fee_amount=10,method='cash'),x.m.Payment(contract=c,amount=40,late_fee_amount=0,method='cash',voided_at=datetime.now())]);x.s.commit()
    old=c.principal_paid_total;module('reporting_v83').attach_payment_totals(x.s,[c]);assert c.principal_paid_total==old==80

def test_reversal_corrects_original_open_drawer_not_authorizers(x):
    cash=module('operations.cash')
    other=x.m.User(organization_id=x.org.id,name='Supervisor',email='supervisor@example.test',role='manager',password_hash='test')
    x.s.add(other);x.s.commit()
    original=cash.open_shift(x.s,x.org.id,x.u.id,100)
    supervisor=cash.open_shift(x.s,x.org.id,other.id,200)
    cash.post_entry(x.s,x.org.id,x.u.id,'payment',1,50,'cash','Cobro')
    correction=cash.reverse_entry(x.s,x.org.id,other.id,'payment_reversal',1,'payment',1,-50,'cash','Correccion')
    assert correction.cash_shift_id==original.id
    assert cash.expected_cash(x.s,original)==100 and cash.expected_cash(x.s,supervisor)==200

def test_reversal_never_modifies_closed_count_or_debits_new_cash(x):
    cash=module('operations.cash');old=cash.open_shift(x.s,x.org.id,x.u.id,100)
    cash.post_entry(x.s,x.org.id,x.u.id,'payment',1,50,'cash','Cobro');cash.close_shift(x.s,x.org.id,x.u.id,old.id,150,'');x.s.commit()
    new=cash.open_shift(x.s,x.org.id,x.u.id,150)
    correction=cash.reverse_entry(x.s,x.org.id,x.u.id,'payment_reversal',1,'payment',1,-50,'cash','Correccion')
    assert correction.cash_shift_id is None and old.counted==150 and cash.expected_cash(x.s,new)==150
