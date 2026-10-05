"""Isolated synthetic data for template regression tests (never loaded by the app)."""
import runpy
from datetime import date, datetime
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace as NS
from urllib.parse import urlencode
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = runpy.run_path(str(ROOT / 'cuotago/dealer_summary.py'))


def fixture_data():
    now = datetime(2026, 10, 5, 10, 0)
    client = NS(id=1, full_name='Cliente de prueba', phone='8095550100', email='qa@example.invalid',
                document_id='PRUEBA-001', address='Datos de prueba, no reales', notes='Seguimiento comercial.', contracts=[])
    asset = NS(id=1, name='Hyundai Sonata Limited', kind='car', brand='Hyundai', model='Sonata Limited',
        vehicle_year=2020, mileage=71300, identifier='PRUEBA-001', serial_number='CHASIS-QA-0001',
        estimated_value=D('800000'), sale_price=D('1000000'), quantity_total=1, available_quantity=1,
        committed_quantity=0, status='available', image_mime='image/webp', image_updated_at=now,
        notes='Unidad de prueba para verificar la interfaz.', investments=[], contracts=[], sales=[], purchases=[], created_at=now)
    expense = NS(id=1, method='transfer', reference='TALLER-QA')
    investment = NS(id=1, amount=D('50000'), description='Preparaci\u00f3n y mantenimiento', category='maintenance',
        investment_date=date(2026,10,1), expense=expense, notes='Cambio de piezas y revisi\u00f3n.')
    asset.investments = [investment]
    sold = NS(**vars(asset)); sold.id=2; sold.status='sold'; sold.available_quantity=0; sold.committed_quantity=1
    sale = NS(id=1, code='CGV-1-000001', asset=sold, client=client, client_id=1, quantity=1,
        status='completed', total_amount=D('950000'), total_cost=D('850000'), profit_amount=D('100000'),
        sale_date=date(2026,10,5), created_at=now, buyer_display=client.full_name,
        unit_price=D('950000'),unit_cost=D('800000'),investment_cost=D('50000'),payment_method='transfer',
        reference='TRANSFER-QA', buyer_phone=client.phone, notes='Nota privada QA',void_reason=None,margin_percent=D('11.76'))
    sold.sales=[sale]
    car2=NS(**vars(asset)); car2.id=3; car2.name='Toyota Corolla'; car2.brand='Toyota';car2.model='Corolla'; car2.image_mime=None; car2.status='assigned';car2.available_quantity=0;car2.committed_quantity=1
    contract=NS(id=1,code='CG-1-000001',client_id=1,client=client,asset_id=3,asset=car2,quantity=1,
        deal_type='credit_sale',status='active',paid_total=D('300000'),balance=D('600000'),total_amount=D('900000'),created_at=now)
    car2.contracts=[contract];client.contracts=[contract]
    promise=NS(id=1, amount=D('50000'), status='pending',contract=contract, promised_date=date(2026,10,15),note='Llamar el d\u00eda anterior.')
    note=NS(id=1,body='Cliente interesado en renovar su veh\u00edculo.',created_at=now,created_by_user_id=1)
    activity=[dict(at=now,title='Unidad registrada',detail='Entrada al inventario.',url=None)]
    common=dict(app_name='CuotaGo',today=date(2026,10,5),dealer_context=None)
    asset_context=dict(common,asset=asset,investments=asset.investments,dealer_finance=SUMMARY['asset_summary'](asset),
        operations=[],operable=True,acquisition_type='purchase',acquisition_origin='Proveedor de prueba',
        acquisition_date=date(2026,10,1),latest_purchase=None,expenses_total=D('50000'),activity=activity)
    sold_context=dict(asset_context,asset=sold,dealer_finance=SUMMARY['asset_summary'](sold),operable=False,
        operations=[dict(kind='sale',icon='home-sales',title=sale.code,person=client.full_name,person_id=1,date=now,
                         status='Completada',voided=False,amount=sale.total_amount,balance=None,url='/sales/1')])
    client_context=dict(common,client=client,contracts=[contract],direct_sales=[sale],related_assets=[sold,car2],
        dealer_finance=SUMMARY['client_summary']([contract],[sale]),balance=D('600000'),paid=D('300000'),
        overdue_count=0,active_count=1,promises=[promise],notes=[note],actors={1:'Operador de prueba'},
        risk=NS(level='good',label='Buen pagador',reason='Sin atrasos registrados'),
        timeline=[dict(kind='sale',title='Venta '+sale.code,detail=sold.name,amount=sale.total_amount,date=now,url='/sales/1'),
                  dict(kind='agreement',title='Acuerdo '+contract.code,detail=car2.name,amount=contract.total_amount,date=now,url='/contracts/1')])
    docs_context=dict(common,tabs=[dict(key='sales',label='Ventas',icon='home-sales'),dict(key='payments',label='Pagos',icon='wallet'),dict(key='statements',label='Estados de cuenta',icon='users')],
        tab='sales',q='',filter_asset=None,filter_client=None,pagination=NS(total=1,pages=1),
        rows=[dict(icon='home-sales',title=sale.code,detail=asset.name,person=client.full_name,date=now,amount=sale.total_amount,
                   voided=False,pdf='/sales/1/receipt.pdf',url='/sales/1/receipt',label='Comprobante de venta')])
    return NS(asset=asset,sold=sold,client=client,contract=contract,sale=sale,asset_context=asset_context,sold_context=sold_context,client_context=client_context,docs_context=docs_context)


def route_url(endpoint, **values):
    if endpoint=='static':
        name=values.pop('filename');base='/static/'+name
    elif endpoint=='main.asset_image':
        values.pop('asset_id',None);base='/qa-photo.webp'
    else:
        routes={'main.dashboard':'/','main.assets':'/assets','main.clients':'/clients','main.asset_detail':'/assets/{asset_id}',
            'main.client_detail':'/clients/{client_id}','main.sale_new':'/sales/new','main.contract_new':'/contracts/new',
            'main.sale_detail':'/sales/{sale_id}','main.contract_detail':'/contracts/{contract_id}',
            'main.documents':'/documents','main.help':'/help', 'main.asset_edit':'/assets/{asset_id}/edit',
            'main.asset_investment_add':'/assets/{asset_id}/investments','main.sale_receipt_pdf':'/sales/{sale_id}/receipt.pdf'}
        base=routes.get(endpoint,'/'+endpoint.replace('main.','').replace('_','/'))
        for key in list(values):
            if '{'+key+'}' in base:base=base.replace('{'+key+'}',str(values.pop(key)))
    anchor=values.pop('_anchor',None)
    q=urlencode({k:v for k,v in values.items() if v is not None})
    return base+('?' + q if q else '')+('#'+anchor if anchor else '')


def template_env(*, real_base=False, permissions=None):
    loaders=[FileSystemLoader(ROOT/'cuotago/templates')]
    if not real_base: loaders.insert(0,DictLoader({'base.html':'{% block styles %}{% endblock %}{% block content %}{% endblock %}{% block scripts %}{% endblock %}'}))
    env=Environment(loader=ChoiceLoader(loaders),autoescape=True,undefined=StrictUndefined)
    label=lambda value: {'car':'Veh\u00edculo','phone':'Celular','purchase':'Compra','credit_sale':'Venta a cr\u00e9dito','available':'Disponible','sold':'Vendido','assigned':'En acuerdo',
        'active':'Activo','completed':'Completada','voided':'Anulada','maintenance':'Mantenimiento','transfer':'Transferencia','cash':'Efectivo'}.get(value,value or 'Sin definir')
    env.globals.update(url_for=route_url,can=lambda p: permissions is None or p in permissions,csrf_token=lambda:'test-csrf',
        money=lambda v:'RD$'+format(D(str(v or 0)),',.2f'),config={'ASSET_VERSION':'1.26.0-ui-v70','APP_VERSION':'1.26.0'},
        app_name='CuotaGo',today=date(2026,10,5),dealer_context=None,statement_wa_link=lambda c:'',wa_link=lambda *a:'',
        asset_kind_label=label,asset_status_label=label,acquisition_type_label=label,investment_category_label=label,
        payment_method_label=label,contract_status_label=label,sale_status_label=label,deal_type_label=label,
        role_label=lambda _:'Propietario',current_user=NS(id=1,role='owner',is_authenticated=True,name='Cuenta de prueba',email='qa@example.invalid',organization=NS(name='Dealer de prueba')),
        request=NS(blueprint='main',endpoint='main.asset_detail',method='GET'),get_flashed_messages=lambda **kw:[])
    return env
