"""Production helpers/templates tested without Flask or customer data."""
import ast
import hashlib
import io
import json
import runpy
import zipfile
from pathlib import Path
from types import SimpleNamespace as NS
from decimal import Decimal as D
import pytest
from dealer_fixtures import ROOT, SUMMARY, fixture_data, template_env, route_url


def functions(file, names, namespace=None):
    tree=ast.parse((ROOT/file).read_text())
    nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
    assert len(nodes)==len(names)
    env=namespace or {}
    for n in nodes:
        if isinstance(n,ast.FunctionDef): n.decorator_list=[]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(ROOT/file),'exec'),env)
    return env


def test_sale_profit_uses_frozen_cost_not_target():
    x=fixture_data();r=SUMMARY['asset_summary'](x.sold)
    assert r['target_profit']==D('150000')
    assert r['direct_profit']==D('100000')
    assert r['direct_cost']==D('850000')
    x.sold.sale_price=D('1100000');x.sold.estimated_value=D('850000')
    assert SUMMARY['asset_summary'](x.sold)['direct_profit']==D('100000')


def test_voided_sales_do_not_count_and_target_absent_is_not_zero_profit():
    x=fixture_data();x.sale.status='voided';x.sold.sale_price=D(0)
    r=SUMMARY['asset_summary'](x.sold)
    assert r['direct_profit']==0 and r['direct_count']==0 and r['target_profit'] is None


def test_multiunit_investment_is_allocated_per_unit():
    a=fixture_data().asset;a.quantity_total=5;a.estimated_value=D(100);a.sale_price=D(110)
    a.investments=[NS(amount=D(75))]
    r=SUMMARY['asset_summary'](a)
    assert (r['investment_unit'],r['lot_cost'],r['target_profit'])==(D(15),D(575),D(-5))


def test_cash_and_credit_receipts_remain_separate():
    x=fixture_data();r=SUMMARY['client_summary']([x.contract],[x.sale])
    assert r['cash_received']==D('950000') and r['agreement_received']==D('300000')
    assert r['received_total']==D('1250000') and r['balance']==D('600000')
    x.contract.status='cancelled';x.sale.status='voided'
    r=SUMMARY['client_summary']([x.contract],[x.sale])
    assert r['received_total']==D('300000') and r['balance']==0 and r['voided_count']==1


@pytest.mark.parametrize('path,ok', [('/clients/1',True),('/collections?q=test#pay',True),('https://bad.invalid',False),('//bad.invalid',False),('/\\bad.invalid',False),('/%5cbad.invalid',False),('/%2fexample.invalid',False),('/%0d%0alocation:x',False),('',False)])
def test_redirect_whitelist(path,ok):
    f=functions('cuotago/workflow.py',['safe_local_path'])['safe_local_path']
    assert f(path) is ok


@pytest.mark.parametrize('text',["=SUM(1,2)",'+1+1','-cmd','@formula',' \t=cmd'])
def test_export_does_not_execute_text_formulas(text):
    assert SUMMARY['csv_cell'](text).startswith("'")
    assert SUMMARY['csv_cell'](D('-23.5'))==D('-23.5')


def test_export_manifest_hashes_and_image_paths():
    import csv
    from pathlib import PurePosixPath
    env=functions('cuotago/business_export.py',['ExportWriter','_with_header','image_export_path'],dict(csv=csv,hashlib=hashlib,io=io,json=json,PurePosixPath=PurePosixPath,csv_cell=SUMMARY['csv_cell']))
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as archive:
        w=env['ExportWriter'](archive)
        w.write_csv('clientes.csv',['id','nombre'],[(1,'=HYPERLINK("x")'),(2,'Normal')])
        w.write_bytes('imagenes/inventario-1.webp',b'test bytes only')
        w.manifest(1,'2026-10-05T00:00:00Z')
        with pytest.raises(ValueError):w.write_bytes('../secret',b'')
    with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as archive:
        manifest=json.loads(archive.read('manifest.json'))
        assert manifest['database_backup'] is False and manifest['automatic_restore'] is False
        for entry in manifest['files']:
            assert hashlib.sha256(archive.read(entry['path'])).hexdigest()==entry['sha256']
        assert manifest['files'][0]['rows']==2
        assert "'=HYPERLINK" in archive.read('clientes.csv').decode('utf-8-sig')
    assert env['image_export_path'](NS(id=3,image_mime='text/html'))==''


@pytest.mark.parametrize('name,key',[('assets/detail.html','asset_context'),('assets/detail.html','sold_context'),('clients/detail.html','client_context'),('documents/center.html','docs_context')])
def test_real_templates_render_and_do_not_inject_user_html(name,key):
    x=fixture_data();x.client.full_name='<script>alert(1)</script>';x.asset.name='<img onerror=alert(1)>'
    rendered=template_env().get_template(name).render(**getattr(x,key))
    assert '<script>alert(1)</script>' not in rendered
    assert '<img onerror=' not in rendered
    assert 'dlr-' in rendered


def test_actions_permissions_and_availability():
    x=fixture_data();tpl=template_env().get_template('assets/detail.html')
    available=tpl.render(**x.asset_context);sold=tpl.render(**x.sold_context)
    assert '/sales/new?asset_id=1' in available and '/contracts/new?asset_id=1' in available
    assert '/sales/new?' not in sold and '/contracts/new?' not in sold
    read_only=template_env(permissions={'inventory.view'}).get_template('assets/detail.html').render(**x.asset_context)
    assert '/sales/new?' not in read_only and 'id="assetInvestmentDialog"' not in read_only


def test_client_without_sales_permission_does_not_request_photos_or_show_cash():
    x=fixture_data();rendered=template_env(permissions={'clients.view','contracts.view','payments.view'}).get_template('clients/detail.html').render(**x.client_context)
    assert 'Compras de contado' not in rendered and '/sales/new' not in rendered
    assert '/qa-photo.webp' not in rendered


def test_context_is_scoped_and_cached():
    class Values(dict):
        def get(self,key,default=None,type=None):
            v=super().get(key,default)
            try:return type(v) if type else v
            except (TypeError,ValueError):return default
    class Query:
        def filter_by(self,**kw):
            self.kw=kw;return self
        def first(self):
            return NS(id=7,name='Unidad') if self.kw=={'id':7,'organization_id':1} else None
    query=Query();store=NS()
    env=functions('cuotago/workflow.py',['origin_context','contextual_url'],dict(g=store,request=NS(values=Values(origin='asset',origin_id='7')),
        current_user=NS(is_authenticated=True,organization_id=1),Asset=NS(query=query),Client=NS(query=query),
        has_permission=lambda u,p:True,url_for=route_url))
    assert env['origin_context']()['url']=='/assets/7'
    assert 'origin=asset' in env['contextual_url']('main.sales')
    del store._dealer_origin
    env['request'].values=Values(origin='asset',origin_id='8')
    assert env['origin_context']() is None
    del store._dealer_origin
    env['request'].values=Values(origin='asset',origin_id='7')
    env['has_permission']=lambda u,p:False
    assert env['origin_context']() is None



def test_operational_status_is_read_only():
    x=fixture_data();a=x.asset;a.status='sold'
    assert SUMMARY['operational_status'](a)=='available'
    assert a.status=='sold'
    a.status='workshop'
    assert SUMMARY['operational_status'](a)=='workshop'
    assert SUMMARY['operational_status'](x.sold)=='sold'


def test_read_only_inventory_views_do_not_commit_status_repairs():
    tree=ast.parse((ROOT/'cuotago/main.py').read_text())
    for name in ['assets','asset_detail','reports']:
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
        calls=[n for n in ast.walk(node) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)]
        assert 'refresh_asset_status' not in [n.func.id for n in calls]


def test_new_components_are_versioned_and_precached():
    worker=(ROOT/'cuotago/static/service-worker.js').read_text()
    base=(ROOT/'cuotago/templates/base.html').read_text()
    for rel in ['css/dealer.css','js/dealer.js']:
        assert rel in worker and rel in base
    assert '1.26.0-ui-v70' in worker
    assert (ROOT/'chatbridge-run.bat').is_file()


def test_sale_form_keeps_preselected_client_and_origin_fields():
    x=fixture_data();env=template_env()
    rendered=env.get_template('sales/form.html').render(form={},clients=[x.client],assets=[],asset_count=0,
        asset_next_page=None,asset_payloads=[],selected_asset_payload=None,request_key='qa',default_date='2026-10-05',
        selected_asset_id=None,selected_client_id=1,dealer_context={'kind':'client','id':1,'url':'/clients/1','icon':'users','label':x.client.full_name})
    from html.parser import HTMLParser
    class Parser(HTMLParser):
        def __init__(self):super().__init__();self.options=[];self.fields={}
        def handle_starttag(self,tag,attrs):
            attrs=dict(attrs)
            if tag=='option' and 'selected' in attrs:self.options.append(attrs.get('value'))
            if tag=='input':self.fields[attrs.get('name')]=attrs.get('value')
    parser=Parser();parser.feed(rendered)
    assert '1' in parser.options
    assert parser.fields['origin']=='client' and parser.fields['origin_id']=='1'
