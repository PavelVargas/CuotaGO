"""Transactional services on real SQLAlchemy/SQLite; PG locks are a separate gate."""
from datetime import date
from decimal import Decimal
import io
import pytest
from PIL import Image
from v83_harness import database, module

@pytest.fixture
def x():
    data=database()
    yield data
    data.s.close(); data.engine.dispose()


def row(x, **kw):
    data=dict(asset_id=x.a.id,quantity=2,unit_cost='150')
    data.update(kw);return data


def create(x,rows=None,state='draft'):
    return module('operations.purchasing').create_order(x.s,x.org.id,x.u.id,x.supplier.id,
        rows if rows is not None else [row(x)],state=state)


def update(x,o,rows=None,confirm=False,revision=None):
    return module('operations.purchasing').update_draft(x.s,x.org.id,x.u.id,o.id,
        o.revision if revision is None else revision,x.supplier.id,
        rows if rows is not None else [row(x,line_id=o.lines[0].id)],confirm=confirm)


def test_draft_empty_persists_without_money_or_stock(x):
    o=create(x,[]);x.s.commit()
    assert o.state=='draft' and o.revision==1 and not o.lines
    assert x.a.quantity_total==10
    assert x.s.query(x.m.Purchase).count()==x.s.query(x.n.MoneyEntry).count()==0


def test_confirm_from_same_editor_no_inventory_changes(x):
    o=create(x);x.s.commit();update(x,o,confirm=True);x.s.commit()
    assert o.state=='sent' and o.revision==2 and x.a.quantity_total==10
    assert module('operations.purchasing').order_totals(o)['ordered']==Decimal('300')


def test_confirm_directly_skips_draft_without_skipping_receipt(x):
    o=create(x,state='sent');x.s.commit();assert o.state=='sent'
    assert x.a.quantity_total==10 and x.s.query(x.m.Purchase).count()==0


@pytest.mark.parametrize('what',['receive','pay'])
def test_draft_cannot_receive_or_pay(x,what):
    api=module('operations.purchasing');o=create(x);x.s.commit()
    with pytest.raises(ValueError):
        if what=='receive':api.receive_order(x.s,x.org.id,x.u.id,o.id,{str(o.lines[0].id):1},'America/Santo_Domingo')
        else:api.pay_supplier(x.s,x.org.id,x.u.id,o.id,100,'cash')
    x.s.rollback();assert x.a.quantity_total==10
    assert x.s.query(x.n.MoneyEntry).count()==0


def test_draft_may_save_no_price_but_not_confirm(x):
    o=create(x,[row(x,unit_cost='')]);x.s.commit()
    assert o.lines[0].unit_cost==0
    with pytest.raises(ValueError):update(x,o,rows=[row(x,line_id=o.lines[0].id,unit_cost='')],confirm=True)
    x.s.rollback();assert o.state=='draft' and o.revision==1


def test_empty_order_cannot_confirm(x):
    with pytest.raises(ValueError):create(x,[],state='sent')


@pytest.mark.parametrize('qty,cost',[('0','2'),('1.5','2'),('1','-1'),('1','NaN'),('1','Infinity'),('1000001','1')])
def test_invalid_numbers_rejected(x,qty,cost):
    with pytest.raises(ValueError):create(x,[row(x,quantity=qty,unit_cost=cost)])


def test_second_tab_cannot_overwrite_or_confirm_stale_draft(x):
    o=create(x);x.s.commit();revision=o.revision
    update(x,o);x.s.commit()
    with pytest.raises(ValueError,match='ventana'):update(x,o,revision=revision,confirm=True)
    x.s.rollback();assert o.state=='draft' and o.revision==2


def test_sent_order_is_not_editable(x):
    o=create(x,state='sent');x.s.commit()
    with pytest.raises(ValueError):update(x,o)


def test_discard_retains_audit_and_has_no_monetary_effect(x):
    o=create(x);x.s.commit();module('operations.purchasing').discard_draft(x.s,x.org.id,x.u.id,o.id,1);x.s.commit()
    assert o.state=='discarded' and o.revision==2 and x.a.quantity_total==10
    assert x.s.query(x.m.TenantAuditLog).filter_by(action='order.discarded').count()==1
    assert x.s.query(x.m.Purchase).count()==0
    with pytest.raises(ValueError):module('operations.purchasing').pay_supplier(x.s,x.org.id,x.u.id,o.id,1,'transfer')


def test_discard_does_not_cancel_confirmed_order(x):
    o=create(x,state='sent');x.s.commit()
    with pytest.raises(ValueError):module('operations.purchasing').discard_draft(x.s,x.org.id,x.u.id,o.id,1)


def test_tenant_boundaries_on_edit_and_discard(x):
    o=create(x);x.s.commit();api=module('operations.purchasing')
    with pytest.raises(LookupError):api.update_draft(x.s,x.other.id,x.v.id,o.id,1,x.supplier.id,[row(x)])
    with pytest.raises(LookupError):api.discard_draft(x.s,x.other.id,x.v.id,o.id,1)
    with pytest.raises(LookupError):api.create_order(x.s,x.other.id,x.v.id,x.supplier.id,[row(x)],state='draft')


def test_line_belongs_to_draft_and_not_another_order(x):
    o=create(x);other=create(x);x.s.commit()
    with pytest.raises(ValueError):update(x,o,[row(x,line_id=other.lines[0].id)])
    x.s.rollback();assert len(o.lines)==1


def test_duplicate_line_id_rejected(x):
    o=create(x);x.s.commit();data=row(x,line_id=o.lines[0].id)
    with pytest.raises(ValueError):update(x,o,[data,data])


def test_replace_lines_preserves_exact_total(x):
    o=create(x);x.s.commit()
    update(x,o,[row(x,unit_cost='12.34',quantity=3),dict(name='Nuevo',kind='phone',quantity=1,unit_cost='2.01')]);x.s.commit()
    assert len(o.lines)==2 and module('operations.purchasing').order_totals(o)['ordered']==Decimal('39.03')


def test_delete_all_draft_lines_does_not_leave_orphans(x):
    o=create(x);x.s.commit();update(x,o,[]);x.s.commit()
    assert not o.lines and x.s.query(x.n.PurchaseOrderLine).count()==0


def test_photo_new_product_is_saved_on_draft_then_transferred_on_receipt(x):
    api=module('operations.purchasing');images=module('operations.order_images')
    source=io.BytesIO();Image.new('RGB',(200,100),'white').save(source,'PNG')
    photo=images.normalize_photo(source.getvalue())
    o=create(x,[dict(name='Vehiculo nuevo',kind='car',quantity=1,unit_cost='5000',photo=photo)])
    x.s.commit();line=o.lines[0]
    assert x.s.query(x.m.Asset).count()==1 and line.photo_data==photo[0]
    update(x,o,[dict(line_id=line.id,name=line.name,kind=line.kind,quantity=1,unit_cost=5000)],confirm=True);x.s.commit()
    api.receive_order(x.s,x.org.id,x.u.id,o.id,{str(o.lines[0].id):1},'America/Santo_Domingo');x.s.commit()
    asset=x.s.get(x.m.Asset,o.lines[0].asset_id)
    assert asset.image_data==photo[0] and asset.image_mime=='image/webp' and o.state=='received'


def test_existing_asset_photo_is_snapshotted_not_overwritten(x):
    x.a.image_mime='image/webp';x.a.image_thumb_data=b'old-photo';x.s.commit()
    o=create(x);x.s.commit();assert o.lines[0].photo_data==b'old-photo'
    update(x,o,[row(x,line_id=o.lines[0].id,photo=(b'new-photo','image/webp'))]);x.s.commit()
    assert o.lines[0].photo_data==b'new-photo' and x.a.image_thumb_data==b'old-photo'


def test_explicit_remove_photo_stays_removed_on_next_save(x):
    x.a.image_mime='image/webp';x.a.image_thumb_data=b'old-photo';x.s.commit()
    o=create(x);x.s.commit();update(x,o,[row(x,line_id=o.lines[0].id,clear_photo=True)]);x.s.commit()
    update(x,o);x.s.commit();assert o.lines[0].photo_data is None and o.lines[0].photo_mime==''


def test_changing_asset_does_not_keep_previous_photo(x):
    x.a.image_mime='image/webp';x.a.image_thumb_data=b'old';x.s.commit();o=create(x);x.s.commit()
    update(x,o,[dict(line_id=o.lines[0].id,name='Distinto',kind='phone',quantity=1,unit_cost='1')]);x.s.commit()
    assert o.lines[0].photo_data is None


def test_receipt_batches_keep_each_delivery_separate(x):
    api=module('operations.purchasing');docs=module('operations.order_documents')
    o=create(x,[row(x,quantity=4),dict(name='Nuevo',kind='other',quantity=3,unit_cost=5)],state='sent');x.s.commit()
    api.receive_order(x.s,x.org.id,x.u.id,o.id,{str(o.lines[0].id):2,str(o.lines[1].id):1},'America/Santo_Domingo');x.s.commit()
    first=docs.receipt_batches(x.s,x.org.id,o.id)[0]
    api.receive_order(x.s,x.org.id,x.u.id,o.id,{str(o.lines[0].id):2,str(o.lines[1].id):2},'America/Santo_Domingo');x.s.commit()
    groups=docs.receipt_batches(x.s,x.org.id,o.id)
    assert len(groups)==2 and [g['units'] for g in groups]==[4,3]
    assert docs.receipt_document(x.s,x.org.id,o.id,first['id'])['units']==3
    with pytest.raises(LookupError):docs.receipt_document(x.s,x.other.id,o.id,first['id'])
    other=create(x,state='sent');x.s.commit()
    with pytest.raises(LookupError):docs.receipt_document(x.s,x.org.id,other.id,first['id'])


def test_replayed_creation_adds_only_one_order(x):
    common=module('operations.common');api=module('operations.purchasing');key='test-order-key-0123456789'
    op,replay=common.operation(x.s,x.org.id,'order_create',key,{'form':{'action':'confirm'}})
    o=create(x,state='sent');op.result_id=str(o.id);x.s.commit()
    op,replay=common.operation(x.s,x.org.id,'order_create',key,{'form':{'action':'confirm'}})
    assert replay and op.result_id==str(o.id) and x.s.query(x.n.PurchaseOrder).count()==1
    with pytest.raises(ValueError):common.operation(x.s,x.org.id,'order_create',key,{'form':{'action':'draft'}})


@pytest.mark.parametrize('raw',[b'not a photo',b'<svg onload="alert(1)"></svg>',b'\x00'*(6*1024*1024+1)])
def test_image_validation_rejects_bad_bytes(raw):
    with pytest.raises(ValueError):module('operations.order_images').normalize_photo(raw)


def test_image_normalization_bounded_and_reencoded():
    buf=io.BytesIO();Image.new('RGB',(1600,900),'white').save(buf,'JPEG')
    data,mime=module('operations.order_images').normalize_photo(buf.getvalue())
    with Image.open(io.BytesIO(data)) as image:
        assert image.width<=1000 and image.height<=750 and image.format=='WEBP'
    assert mime=='image/webp'
