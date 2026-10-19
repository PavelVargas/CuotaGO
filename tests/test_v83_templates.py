"""Strict Jinja rendering and UI82 preservation; not an HTTP smoke test."""
import ast
from datetime import date,datetime,timedelta
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from dealer_fixtures import template_env
from v83_harness import database,module
ROOT=Path(__file__).resolve().parents[1]


def context():
    d=database();m,n=d.m,d.n
    c=m.Contract(organization_id=d.org.id,client=d.c,asset=d.a,code='QA-83',deal_type='credit_sale',status='active',quantity=1,total_amount=1000,base_amount=700,down_payment=0,installment_amount=500,daily_late_interest=0,frequency='monthly',start_date=date.today(),first_due_date=date.today()+timedelta(days=30))
    c.installments.append(m.Installment(sequence=1,amount=1000,paid_amount=0,due_date=c.first_due_date))
    d.s.add(c);d.s.flush()
    p=m.Payment(contract=c,amount=100,late_fee_amount=0,method='transfer',receipt_code='QA-REC-83',paid_at=datetime.utcnow())
    d.s.add(p);d.s.flush()
    order=module('operations.purchasing').create_order(d.s,d.org.id,d.u.id,d.supplier.id,[dict(asset_id=d.a.id,quantity=2,unit_cost='100')])
    d.s.commit()
    page=lambda items:NS(items=items,has_prev=False,has_next=False,page=1,pages=1,total=len(items))
    common=dict(active=None,expected=0,entries=[],page=page([]),payment=p,suppliers=[d.supplier],assets=[d.a],order=order,totals=module('operations.purchasing').order_totals(order),columns=['full_name','document_id'],batch=NS(id=1,digest='sha',kind='clients'),rows=[dict(full_name='Prueba',document_id='QA-01')],people=[d.u],client=d.c,grants=[],link=None,control=None,checks=[('Esquema','Pendiente','Validar PostgreSQL')],mfa=None,devices=[],current_device_id=None,secret='JBSWY3DPEHPK3PXP',uri='otpauth://totp/QA',codes=['TEST-CODE-ONE'],customer=d.c.full_name,business=d.org.name,currency='DOP',data=[dict(id=c.id,status='active',description=d.a.name,balance='900',total='1000',principal_paid='100',installments=[dict(due=date.today(),amount='1000',remaining='900')],receipts=[dict(code=p.receipt_code,day=date.today(),amount='100',reversed=False)])])
    return d,common,page

PAGES=['index','cash','reversal','orders','order_new','order_detail','imports','import_preview','bank','collectors','portal_manage','controls','readiness','error']
TEMPLATES=['operations/'+name+'.html' for name in PAGES]+['security/index.html','security/enroll.html','security/recovery.html','portal/entry.html','portal/statement.html','auth/mfa.html']

@pytest.mark.parametrize('name',TEMPLATES)
def test_new_templates_strict_render(name):
    d,ctx,page=context()
    try:
        env=template_env(real_base=True)
        env.globals['request']=NS(blueprint='ops',endpoint='ops.index',method='GET',args={})
        if name.endswith('/orders.html'):
            ctx.update(page=page([ctx['order']]),totals=module('operations.purchasing').order_totals)
        if name.endswith('/collectors.html'):ctx['page']=page([d.c])
        if name.endswith('/imports.html'):ctx['columns']={'clients':['full_name','document_id']}
        html=env.get_template(name).render(**ctx)
        assert '<script' not in str(d.c.full_name) # fixture is deliberately plain
        assert '<html' in html and 'undefined' not in html.lower()
        assert 'operations-v83.css' in html or name=='auth/mfa.html'
    finally:d.s.close();d.engine.dispose()


def test_all_templates_parse_and_new_links_resolve():
    env=template_env(real_base=True)
    for path in (ROOT/'cuotago/templates').rglob('*.html'):
        env.parse(path.read_text(encoding='utf-8'))
    endpoints=set()
    for path in (ROOT/'cuotago').rglob('*.py'):
        tree=ast.parse(path.read_text(encoding='utf-8'));bps={}
        for node in tree.body:
            if isinstance(node,ast.Assign) and isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id=='Blueprint':
                bps[node.targets[0].id]=node.value.args[0].value
        for node in ast.walk(tree):
            if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
            for deco in node.decorator_list:
                if isinstance(deco,ast.Call) and isinstance(deco.func,ast.Attribute) and isinstance(deco.func.value,ast.Name) and deco.func.attr in ('route','get','post'):
                    var=deco.func.value.id
                    prefix=bps.get(var)
                    if prefix:endpoints.add(prefix+'.'+node.name)
                    elif var=='app':endpoints.add(node.name)
    from jinja2 import nodes
    for folder in ('operations','security','portal'):
        for path in (ROOT/'cuotago/templates'/folder).glob('*.html'):
            tree=env.parse(path.read_text())
            for call in tree.find_all(nodes.Call):
                if isinstance(call.node,nodes.Name) and call.node.name=='url_for' and call.args and isinstance(call.args[0],nodes.Const):
                    target=call.args[0].value
                    assert target=='static' or target in endpoints, (path.name,target)


def test_ui82_icon_layout_identity_is_not_replaced():
    css=(ROOT/'cuotago/static/css/launcher-v82.css').read_text()
    assert 'repeat(4, minmax(0, 1fr))' in css and 'repeat(3' not in css
    new=(ROOT/'cuotago/static/css/operations-v83.css').read_text()
    assert 'dashboard-home' not in new and 'launcher-grid' not in new
