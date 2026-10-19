"""Synthetic Jinja fixtures: no Flask server, private records or network required."""
from pathlib import Path
import sys, runpy, json, mimetypes, traceback
from datetime import date, datetime
from types import SimpleNamespace as NS
from jinja2 import meta
from urllib.parse import urlparse, parse_qs
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tests'))
from dealer_fixtures import fixture_data, template_env, route_url
D=fixture_data();env=template_env(real_base=True)
env.globals['config'].update(ASSET_VERSION='1.26.8-ui-v78',APP_VERSION='1.26.8',PUSH_NOTIFICATIONS_ENABLED=False)
env.globals['current_user'].organization.currency='DOP'
route_map={'main.dashboard':'/','main.purchase_new':'/purchases/new','main.contract_new':'/contracts/new','main.client_new':'/clients/new','main.asset_new':'/assets/new','main.sale_new':'/sales/new','main.reports':'/reports','main.settings':'/settings','main.purchases':'/purchases','main.contracts':'/contracts','main.clients':'/clients','main.assets':'/assets','main.sales':'/sales','main.expenses':'/expenses'}
def url(endpoint,**kw):
 return route_map[endpoint] if endpoint in route_map and not kw else route_url(endpoint,**kw)
env.globals['url_for']=url
env.globals['frequency_label']=lambda f:'Mensual'
D.asset.image_mime=None
D.client.sales=[D.sale]
D.contract.progress_percent=33.33;D.contract.late_fee_balance=3000
D.contract.next_installment=NS(due_date=date(2026,10,15),remaining=75000)
D.contract.installments=[];D.contract.frequency='monthly'
D.contract.daily_late_interest=100;D.contract.down_payment=100000;D.contract.start_date=date(2026,10,1)
D.contract.first_due_date=date(2026,11,1);D.contract.base_amount=800000;D.contract.profit_amount=100000
D.contract.payments=[];D.contract.notes='';D.contract.schedule_changes=[]
D.asset.expected_margin_percent=25;D.asset.expected_profit_per_unit=200000
D.asset.acquisition_type='purchase';D.asset.acquisition_date=date(2026,10,1);D.asset.acquisition_origin='';D.asset.total_investment=850000
page=NS(total=3,pages=1,has_prev=False,has_next=False,page=1)
common=dict(app_name='CuotaGo',form={},clients=[D.client],assets=[D.asset],today=date(2026,10,19),default_date='2026-10-19',default_start='2026-10-19',default_due='2026-11-19',q='',status='',supplier='',kind='',brand='',pagination=page,dealer_context=None,selected_client_id=None)
def report_context():
 template=env.loader.get_source(env,'reports/index.html')[0]
 names=meta.find_undeclared_variables(env.parse(template));data={k:0 for k in names if k not in env.globals and k!='icon'}
 data.update(period_label='Este mes',report_period='month',report_status='all',selected_client_id=None,report_clients=[D.client],receivable=4525000,overdue_total=265000,period_collected=890000,direct_sales_period_total=2400000,direct_sales_period_count=2,direct_sales_period_units=2,active_count=20,period_payment_count=12,overdue_clients_count=3,cash_flow_net=3100000,business_income_total=3290000,profit_expected=450000,chart_has_data=True,chart_max_value=1500000,chart_first_label='01 oct',chart_last_label='31 oct',chart_title='Este mes',chart_total=3290000,chart_expense_total=190000,chart_points_svg='20,155 200,110 380,135 560,65 740,85 980,20',chart_expense_points_svg='20,155 200,145 380,150 560,145 740,110 980,130',chart_area_svg='20,155 200,110 380,135 560,65 740,85 980,20 980,155',portfolio_health_percent=85,overdue_ratio_percent=5.86,expense_ratio_percent=5.7,cash_flow_margin_percent=94,expenses_period_total=190000,capital_total=7000000,capital_recovered=1000000,capital_pending=6000000,profit_realized=80000,profit_pending=370000,financed_total=9000000,direct_sales_period_profit=270000,inventory_available_value=2450000,inventory_sale_value=3500000,inventory_potential_profit=1050000,inventory_margin_percent=42.85,inventory_status_counts=NS(available=8,maintenance=2,workshop=1,on_loan=4,sold=3),payment_method_totals=NS(cash=150000,transfer=400000,deposit=200000,card=100000,other=40000),expense_category_totals=[],inventory_opportunities=[],recent_activity=[],overdue_aging=[NS(key='1_7',label='1 a 7 d\u00edas',amount=265000,percent=100,count=3)],overdue_attention=[NS(client=D.client,installments=3,days=4,amount=265000)])
 return data
modules=runpy.run_path(str(ROOT/'cuotago/module_catalog.py'))['MODULE_CATALOG']
modules=[NS(**m) for m in modules if m['slug']!='notifications']
contexts={
 '/':('dashboard.html',dict(modules=modules,module_status={},receivable=4525000,overdue_total=265000,due_today_count=5,reminder_count=3,show_home_status=True)),
 '/reports':('reports/index.html',report_context()),
 '/settings':('settings/index.html',{}),
 '/contracts':('contracts/list.html',dict(contracts=[D.contract]*3,visible_active=3,visible_overdue=3,visible_balance=1800000)),
 '/contracts/new':('contracts/form.html',dict(agreement_inventory={'items':[]})),
 '/purchases/new':('purchases/form.html',dict(suppliers=[NS(id=1,name='Proveedor de prueba',phone='8095550100')],rows=[dict(mode='existing',quantity=1)])),
 '/clients/new':('clients/form.html',dict(client=None)),
 '/clients':('clients/list.html',dict(status='all')),
 '/assets/new':('assets/form.html',dict(asset=None)),
 '/assets':('assets/list.html',dict(brand_options=['Hyundai'],inventory_summary=NS(available_units=1,maintenance_units=0,workshop_units=0,cost_value=800000,potential_profit=200000))),
 '/collections':('collections/list.html',dict(collection_rows=[],due_today=[],upcoming=[],overdue=[],overdue_total=265000)),
 '/sales/new':('sales/form.html',dict(request_key='test-key',selected_asset_id=None,selected_asset_payload=None,asset_payloads=[],asset_count=0,asset_next_page=None)),
 '/purchases':('purchases/list.html',dict(filtered_order_count=1,order_count=1,supplier_options=[],invested=800000,month_invested=800000,month_order_count=1,average_order=800000,top_supplier_name='Proveedor de prueba',top_supplier_total=800000,orders=[NS(code='CGC-00001',purchase_date=date(2026,10,19),supplier='Proveedor de prueba',units=1,reference='FAC-001',total=800000,lines=[NS(asset=D.asset,notes='',quantity=1,unit_cost=800000,total_cost=800000)])])),
 '/expenses':('expenses/index.html',dict(selected_asset=None,selected_asset_id=None,period='month',all_expense_total=190000,asset_totals={},today_value=date(2026,10,19),total=190000,category_totals=[],top_categories=[],method_totals=[],expenses=[],expense_category_label=lambda s:s)),
}

contexts['/assets/1'] = ('assets/detail.html', D.asset_context)
contexts['/clients/1'] = ('clients/detail.html', D.client_context)
