"""HTTP/PostgreSQL acceptance for the V84 editor; explicit isolated test DB only.
These tests are not covered by the SQLite/DOM suite. Run tools/run_checks.py
--postgres after installing test requirements and configuring *_test database.
"""
import io
import os
import uuid

import pytest
if os.environ.get('CUOTAGO_RUN_PG_TESTS') != '1':
    pytest.skip('Explicit PostgreSQL opt-in required', allow_module_level=True)
pytest.importorskip('flask')
from PIL import Image
from test_dealer_postgres import app_data
from test_v83_postgres import login, post
from cuotago.extensions import db
from cuotago.models import Asset, Supplier, Organization
from cuotago.operations.models import PurchaseOrder, OrderReceipt


def supplier_id(app, org):
    with app.app_context():
        row = Supplier(organization_id=org, name='Proveedor QA V84')
        db.session.add(row); db.session.commit()
        return row.id


def png_upload():
    data = io.BytesIO(); Image.new('RGB', (24, 18), 'white').save(data, 'PNG')
    data.seek(0)
    return data, 'vehiculo-qa.png'


def test_draft_photo_confirm_partial_receipts_and_print(app_data):
    app, ids = app_data; client = login(app); sid = supplier_id(app, ids['org'])
    fields = dict(supplier_id=str(sid), action='draft', line_asset_id='',
        line_name='Vehiculo nuevo QA', line_kind='car', line_quantity='3',
        line_unit_cost='900', line_id='', line_key='new-photo-line', line_clear_photo='0')
    response = post(client, '/operations/orders/new', dict(fields, **{'photo_new-photo-line': png_upload()}))
    assert response.status_code == 303
    with app.app_context():
        order = PurchaseOrder.query.one(); oid = order.id
        assert order.state == 'draft' and order.revision == 1
        line_id = order.lines[0].id
        assert order.lines[0].photo_mime == 'image/webp'
        assert Asset.query.count() == 1  # no stock created by saving a draft
    assert client.get(f'/operations/orders/{oid}/conduce').status_code == 400
    image = client.get(f'/operations/orders/{oid}/lines/{line_id}/photo')
    assert image.status_code == 200 and image.mimetype == 'image/webp'
    assert 'no-store' in image.headers['Cache-Control']
    fields.update(action='confirm', revision='1', line_id=str(line_id))
    key = uuid.uuid4().hex
    for _ in range(2):
        assert post(client, f'/operations/orders/{oid}/edit', fields, key).status_code == 303
    with app.app_context():
        order = db.session.get(PurchaseOrder, oid)
        assert order.state == 'sent' and order.revision == 2 and Asset.query.count() == 1
        lid = order.lines[0].id
    for route in ('print', 'conduce'):
        assert client.get(f'/operations/orders/{oid}/{route}').status_code == 200
    key = uuid.uuid4().hex
    for _ in range(2):
        assert post(client, f'/operations/orders/{oid}/receive', {f'qty_{lid}': '1'}, key).status_code == 302
    with app.app_context():
        order = db.session.get(PurchaseOrder, oid)
        assert order.state == 'partial' and order.lines[0].received == 1
        product = db.session.get(Asset, order.lines[0].asset_id)
        assert product.quantity_total == 1 and product.image_mime == 'image/webp'
        receipt_id = OrderReceipt.query.one().id
    receipt = client.get(f'/operations/orders/{oid}/receipts/{receipt_id}/print')
    assert receipt.status_code == 200 and b'Precio unitario' not in receipt.data
    assert post(client, f'/operations/orders/{oid}/receive', {f'qty_{lid}': '2'}).status_code == 302
    with app.app_context():
        assert db.session.get(PurchaseOrder, oid).state == 'received'
        assert OrderReceipt.query.count() == 2
    # The first receipt stays an independent delivery after a later reception.
    assert client.get(f'/operations/orders/{oid}/receipts/{receipt_id}/print').status_code == 200


def test_saved_draft_revision_conflict_and_discard(app_data):
    app, ids = app_data; client = login(app); sid = supplier_id(app, ids['org'])
    assert post(client, '/operations/orders/new', {'supplier_id': sid, 'action': 'draft'}).status_code == 303
    with app.app_context(): oid = PurchaseOrder.query.one().id
    fields = {'supplier_id': sid, 'action': 'draft', 'revision': '1', 'note': 'Primera ventana'}
    assert post(client, f'/operations/orders/{oid}/edit', fields).status_code == 303
    fields['note'] = 'Ventana atrasada'
    result = client.post(f'/operations/orders/{oid}/edit', data=dict(fields, request_key=uuid.uuid4().hex),
                         headers={'Accept': 'application/json'})
    assert result.status_code == 400 and result.json['ok'] is False
    with app.app_context():
        order = db.session.get(PurchaseOrder, oid)
        assert order.note == 'Primera ventana' and order.revision == 2
    key = uuid.uuid4().hex
    for _ in range(2):
        assert post(client, f'/operations/orders/{oid}/discard', {'revision': '2'}, key).status_code == 303
    with app.app_context():
        assert db.session.get(PurchaseOrder, oid).state == 'discarded'
        assert Asset.query.count() == 1 and OrderReceipt.query.count() == 0


def test_private_photos_catalog_and_receipts_are_tenant_scoped(app_data):
    app, ids = app_data; client = login(app)
    with app.app_context():
        from cuotago.operations.purchasing import create_order
        other = Organization(name='Other tenant QA'); db.session.add(other); db.session.flush()
        supplier = Supplier(organization_id=other.id, name='Private supplier'); db.session.add(supplier); db.session.flush()
        asset = Asset(organization_id=other.id, name='UNIQUE_FOREIGN_VEHICLE_84', kind='car',
                      quantity_total=1, estimated_value=100, image_mime='image/png', image_data=b'not-public')
        db.session.add(asset); db.session.flush()
        order = create_order(db.session, other.id, ids['user'], supplier.id,
                             [dict(asset_id=asset.id, quantity=1, unit_cost=100)])
        db.session.commit(); aid, oid, lid = asset.id, order.id, order.lines[0].id
    assert client.get('/operations/orders/catalog?q=UNIQUE_FOREIGN_VEHICLE_84').json['items'] == []
    for path in [f'/operations/orders/catalog/{aid}/photo', f'/operations/orders/{oid}',
                 f'/operations/orders/{oid}/edit', f'/operations/orders/{oid}/conduce',
                 f'/operations/orders/{oid}/lines/{lid}/photo',
                 f'/operations/orders/{oid}/receipts/1/print']:
        assert client.get(path).status_code == 404, path


def test_missing_csrf_cannot_save_a_draft(app_data):
    app, ids = app_data; client = login(app); sid = supplier_id(app, ids['org'])
    app.config['WTF_CSRF_ENABLED'] = True
    assert post(client, '/operations/orders/new', {'supplier_id': sid, 'action': 'draft'}).status_code == 400
    with app.app_context(): assert PurchaseOrder.query.count() == 0
