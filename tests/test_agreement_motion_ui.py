"""Photo-picker and motion regressions. No production database is used.

Run with pytest -q tests/test_agreement_motion_ui.py. Existing PostgreSQL
integration tests remain in test_app.py and require TEST_DATABASE_URL.
"""
import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / 'cuotago/main.py'

def function(name, namespace):
    tree = ast.parse(MAIN.read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    assert not node.decorator_list
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(MAIN), 'exec'), namespace)
    return namespace[name]

@pytest.fixture
def templates():
    env = Environment(loader=ChoiceLoader([
        DictLoader({'base.html': '{% block body_class %}{% endblock %}{% block styles %}{% endblock %}{% block content %}{% endblock %}{% block scripts %}{% endblock %}'}),
        FileSystemLoader(ROOT/'cuotago/templates'),
    ]), autoescape=True, undefined=StrictUndefined)
    env.globals.update(url_for=lambda endpoint, **kw: '/'+endpoint, config={'ASSET_VERSION':'qa'},
                       can=lambda _: True, csrf_token=lambda:'test-token')
    return env

def render(env, **overrides):
    values=dict(app_name='CuotaGo',form={},clients=[],assets=[],default_start='2026-10-05',default_due='2026-11-05',agreement_inventory={'items':[]})
    values.update(overrides)
    return env.get_template('contracts/form.html').render(**values)

def test_all_original_agreement_inputs_are_retained(templates):
    names=set(re.findall(r'name="([^"]+)"',render(templates)))
    assert {'csrf_token','request_key','client_id','client_name','client_phone','asset_id',
        'asset_name','asset_kind','asset_identifier','asset_stock_quantity','quantity',
        'deal_type','unit_price','profit_margin_percent','installment_count','frequency',
        'first_due_date','total_amount','installment_amount','down_payment','start_date',
        'down_payment_method','down_payment_reference','daily_late_interest','notes'} <= names
    assert 'asset_image' in names


def test_optional_new_photo_is_permission_scoped(templates):
    templates.globals['can']=lambda permission: permission!='inventory.manage'
    html=render(templates)
    assert 'name="asset_image"' not in html
    assert 'data-asset-mode="new"' not in html
    assert 'data-asset-mode="existing"' in html


def test_empty_inventory_keeps_inline_creation_and_does_not_invent_photos(templates):
    html=render(templates)
    assert 'data-asset-mode="new"' in html
    assert 'agFallback-phone' in html
    assert 'unsplash' not in html and '<img' not in html
    assert 'enctype="multipart/form-data"' in html


def test_jinja_escapes_product_names_and_embedded_json(templates):
    name='<script>alert(1)</script>'
    asset=SimpleNamespace(id=5,name=name,estimated_value=1,sale_price=2,available_quantity=1,identifier='X')
    html=render(templates, assets=[asset],agreement_inventory={'items':[{'id':5,'name':name}]})
    assert name not in html
    assert '&lt;script&gt;' in html and r'\u003cscript\u003e' in html


@pytest.mark.parametrize('selected', [None,1,12,25,'25'])
def test_bootstrap_restores_selected_item_outside_first_page(selected):
    items=[SimpleNamespace(id=i) for i in range(1,31)]
    bootstrap=function('_agreement_inventory_bootstrap', {'_agreement_asset_payload':lambda a:{'id':a.id}})
    data=bootstrap(items,selected)
    assert len(data['items']) <= 13
    ids=[row['id'] for row in data['items']]
    assert len(set(ids))==len(ids)
    if selected is not None: assert int(selected) in ids


def test_agreement_payload_cannot_invoke_sales_photo_write():
    original={'id':9,'image_url':'/assets/9/image?thumb=1','full_image_url':'/assets/9/image','photo_upload_url':'/api/sales/assets/9/photo'}
    payload=function('_agreement_asset_payload',{'_sale_asset_payload':lambda _:dict(original)})
    actual=payload(object())
    assert 'photo_upload_url' not in actual
    assert actual['image_url']==original['image_url']
    assert 'photo_upload_url' in original


def test_lookup_security_and_no_store():
    tree=ast.parse(MAIN.read_text(encoding='utf-8'))
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='agreement_assets_api')
    decorators=[ast.unparse(n) for n in node.decorator_list]
    assert 'login_required' in decorators
    assert "permission_required('contracts.create')" in decorators
    assert "permission_required('inventory.view')" in decorators
    code=ast.unparse(node)
    assert 'private, no-store' in code and 'per_page=12' in code
    assert '_sale_inventory_query(q, kind)' in code


def test_choices_filter_available_stock_before_limit():
    tree=ast.parse(MAIN.read_text(encoding='utf-8'))
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='agreement_form_choices')
    code=ast.unparse(node)
    assert '_sale_inventory_query().limit(60).all()' in code
    assert 'asset_candidates' not in code


def test_optional_photo_uses_existing_optimizer_before_database_creation():
    code=MAIN.read_text(encoding='utf-8').split('def contract_new():',1)[1].split('@main_bp.get("/contracts/<int:contract_id>")',1)[0]
    assert code.index('read_asset_image_upload(request.files.get("asset_image"))') < code.index('db.session.add(client)')
    assert 'image_thumb_data=asset_image[2]' in code
    assert 'asset is None and has_permission(current_user, "inventory.manage")' in code
    assert 'request_key' in code and 'daily_late_interest' in code


def test_motion_is_progressive_and_never_intercepts_navigation():
    js=(ROOT/'cuotago/static/js/motion.js').read_text(encoding='utf-8')
    assert 'preventDefault(' not in js and 'location.assign(' not in js and 'fetch(' not in js
    assert 'pagereveal' in js and 'pagehide' in js and 'pageshow' in js
    assert "fill: 'none'" in js and 'prefers-reduced-motion: reduce' in js
    assert 'sessionStorage.removeItem(storageKey)' in js
    assert 'event.defaultPrevented' in js and "hasAttribute('download')" in js


def test_motion_has_one_owner_and_excludes_reduced_motion():
    app=(ROOT/'cuotago/static/js/app.js').read_text(encoding='utf-8')
    css=(ROOT/'cuotago/static/css/motion.css').read_text(encoding='utf-8')
    assert 'pwaMotionStyle' not in app
    assert '@view-transition { navigation:auto; }' not in css
    assert '@view-transition { navigation:none; }' in css
    assert 'view-transition-name:none' in css
    assert 'view-transition-name:cuotago-content' not in css
    assert 'pointer-events:none' in css
    base=(ROOT/'cuotago/templates/base.html').read_text(encoding='utf-8')
    assert base.index("filename='js/motion.js'") < base.index('</head>')
    assert 'defer' in base.split("filename='js/motion.js'", 1)[1].split('</script>', 1)[0]


def test_new_code_is_versioned_and_in_the_static_worker():
    version=(ROOT/'VERSION.txt').read_text().strip()
    config=(ROOT/'config.py').read_text(encoding='utf-8')
    assert f'APP_VERSION = "{version}"' in config
    worker=(ROOT/'cuotago/static/service-worker.js').read_text(encoding='utf-8')
    for name in ['css/agreements.css','css/motion.css','js/agreements.js','js/motion.js']:
        assert '/static/'+name in worker
        assert (ROOT/'cuotago/static'/name).exists()
    assert (ROOT/'chatbridge-run.bat').exists()
