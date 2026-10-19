"""Actual route-helper bodies with controlled requests, not a Flask HTTP claim."""
import ast
import io
from pathlib import Path
from types import SimpleNamespace as NS
import hashlib
import re
import pytest
from PIL import Image
from v83_harness import database,module,load
ROOT=Path(__file__).resolve().parents[1]

class Form(dict):
    def getlist(self,key):
        value=self.get(key,[])
        return value if isinstance(value,list) else [value]


def helper(name,namespace):
    tree=ast.parse((ROOT/'cuotago/operations/routes.py').read_text())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    node.decorator_list=[]
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<actual-route-helper>','exec'),namespace)
    return namespace[name]


def request_rows(data,files=None):
    load()
    image=module('operations.order_images')
    env=dict(request=NS(form=Form(data),files=files or {}),re=re,hashlib=hashlib,
        normalize_photo=image.normalize_photo,MAX_PHOTO_BYTES=image.MAX_PHOTO_BYTES)
    return helper('_order_rows',env)()


def fields(**kw):
    data=dict(line_asset_id='',line_name='Nuevo vehiculo',line_kind='car',line_quantity='1',line_unit_cost='2',line_key='safe-key-123',line_id='',line_clear_photo='0')
    data.update(kw);return data


def test_multipart_preserves_line_keys_and_photo_hash():
    buf=io.BytesIO();Image.new('RGB',(10,10),'white').save(buf,'PNG');raw=buf.getvalue()
    class Upload(io.BytesIO):filename='photo.png'
    rows,photos=request_rows(fields(),{'photo_safe-key-123':Upload(raw)})
    assert photos['safe-key-123']==hashlib.sha256(raw).hexdigest()
    assert rows[0]['photo'][1]=='image/webp' and rows[0]['quantity']=='1'


@pytest.mark.parametrize('changes',[
    dict(line_quantity=['1','2']),dict(line_key=['first','second']),dict(line_key='../invalid'),
    dict(line_key=''),dict(line_asset_id=['']*101,line_name=['N']*101,line_kind=['car']*101,line_quantity=['1']*101,line_unit_cost=['2']*101),
])
def test_malformed_parallel_fields_rejected(changes):
    with pytest.raises(ValueError):request_rows(fields(**changes))


def test_empty_placeholder_is_not_saved_as_a_product():
    rows,_=request_rows(fields(line_name='',line_unit_cost=''))
    assert rows==[]


def test_duplicate_upload_keys_rejected():
    data={key:[val,val] for key,val in fields().items()}
    with pytest.raises(ValueError):request_rows(data)


def test_all_order_endpoints_have_permissions():
    tree=ast.parse((ROOT/'cuotago/operations/routes.py').read_text())
    expected={'orders':'purchases.view','order_catalog':'purchases.manage','order_new':'purchases.manage',
        'order_edit':'purchases.manage','order_discard':'purchases.manage','order_asset_photo':'purchases.view',
        'order_line_photo':'purchases.view','order_print':'purchases.view','order_conduce':'purchases.view',
        'order_receipt_print':'purchases.view'}
    for name,permission in expected.items():
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
        assert any(isinstance(d,ast.Call) and isinstance(d.func,ast.Name) and d.func.id=='permission_required'
                   and d.args[0].value==permission for d in node.decorator_list),name


def test_draft_print_rejected_and_receipt_scoped_to_order():
    x=database()
    try:
        api=module('operations.purchasing');docs=module('operations.order_documents')
        o=api.create_order(x.s,x.org.id,x.u.id,x.supplier.id,[dict(asset_id=x.a.id,quantity=2,unit_cost=5)],state='draft');x.s.commit()
        env=dict(db=NS(session=x.s),org=lambda:x.org.id,scoped=module('operations.common').scoped,
            PurchaseOrder=x.n.PurchaseOrder,receipt_document=docs.receipt_document,order_totals=api.order_totals,
            STATE_LABELS=docs.STATE_LABELS,utcnow=module('business_time').utcnow,
            render_template=lambda path,**context:context)
        printer=helper('_print_order',env)
        with pytest.raises(ValueError):printer(o.id,'conduce')
        o.state='sent';x.s.commit()
        doc=printer(o.id,'conduce');assert doc['print_rows'][0]['quantity']==2
        with pytest.raises(LookupError):printer(o.id,'receipt',1234)
        env['org']=lambda:x.other.id
        with pytest.raises(LookupError):printer(o.id,'conduce')
    finally:x.s.close();x.engine.dispose()


def test_migration_is_additive_and_uses_existing_entrypoint():
    source=(ROOT/'cuotago/migrations_v84.py').read_text()
    assert 'ADD COLUMN IF NOT EXISTS' in source and 'pg_advisory_xact_lock' in source
    for forbidden in ['DROP TABLE','TRUNCATE','DELETE FROM','UPDATE purchases','UPDATE assets']:
        assert forbidden not in source
    chain=(ROOT/'cuotago/migrations_v83.py').read_text()
    assert 'return migrate_orders(engine) or changed' in chain
    assert '_is_v83_current(engine) and orders_current(engine)' in chain
