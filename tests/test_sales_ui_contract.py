"""Focused regression tests; no application server or production database is used.

Run: pytest -q tests/test_sales_ui_contract.py
Query tests execute the production helper against isolated SQLAlchemy models.
The existing test_app.py suite remains the PostgreSQL integration suite.
"""
import ast
import io
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, and_, case, create_engine, func, or_
from sqlalchemy.orm import Session, declarative_base, relationship, selectinload

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / 'cuotago/main.py'


def production_function(name, namespace):
    tree = ast.parse(MAIN.read_text(encoding='utf-8'))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    assert not function.decorator_list, 'Only undecorated helpers are extracted'
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(MAIN), 'exec'), namespace)
    return namespace[name]


@pytest.fixture
def inventory():
    Base = declarative_base()

    class Asset(Base):
        __tablename__ = 'assets'
        id = Column(Integer, primary_key=True)
        organization_id = Column(Integer, nullable=False)
        quantity_total = Column(Integer, default=1)
        status = Column(String, default='available')
        kind = Column(String, default='car')
        name = Column(String, default='QA unit')
        brand = Column(String)
        model = Column(String)
        identifier = Column(String)
        serial_number = Column(String)
        vehicle_year = Column(Integer)
        created_at = Column(DateTime, default=datetime.utcnow)
        sales = relationship('Sale', back_populates='asset')
        contracts = relationship('Contract', back_populates='asset')
        investments = relationship('Investment', back_populates='asset')

    class Sale(Base):
        __tablename__ = 'sales'
        id = Column(Integer, primary_key=True)
        asset_id = Column(Integer, ForeignKey('assets.id'))
        quantity = Column(Integer, default=1)
        status = Column(String, default='completed')
        asset = relationship('Asset', back_populates='sales')

    class Contract(Base):
        __tablename__ = 'contracts'
        id = Column(Integer, primary_key=True)
        asset_id = Column(Integer, ForeignKey('assets.id'))
        quantity = Column(Integer, default=1)
        status = Column(String, default='active')
        deal_type = Column(String, default='credit_sale')
        asset = relationship('Asset', back_populates='contracts')

    class Investment(Base):
        __tablename__ = 'investments'
        id = Column(Integer, primary_key=True)
        asset_id = Column(Integer, ForeignKey('assets.id'))
        asset = relationship('Asset', back_populates='investments')

    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        Asset.query = session.query(Asset)
        query = production_function('_sale_inventory_query', dict(
            db=SimpleNamespace(session=session), Asset=Asset, Sale=Sale, Contract=Contract,
            current_user=SimpleNamespace(organization_id=1), func=func, case=case,
            or_=or_, and_=and_, selectinload=selectinload,
        ))
        yield SimpleNamespace(session=session, Asset=Asset, Sale=Sale, Contract=Contract, query=query)
    engine.dispose()


def test_inventory_filters_before_pagination_and_is_tenant_scoped(inventory):
    x = inventory
    for n in range(75):
        a = x.Asset(id=n+1, organization_id=1, name='Sold item', quantity_total=1)
        x.session.add(a)
        x.session.add(x.Sale(asset=a, quantity=1, status='completed'))
    x.session.add_all([
        x.Asset(id=90, organization_id=1, name='Available after old limit'),
        x.Asset(id=91, organization_id=2, name='Other company'),
        x.Asset(id=92, organization_id=1, status='workshop'),
        x.Asset(id=93, organization_id=1, status='maintenance'),
    ])
    x.session.commit()
    assert [a.id for a in x.query().limit(12)] == [90]


@pytest.mark.parametrize('status,deal_type,available', [
    ('active', 'credit_sale', False), ('completed', 'credit_sale', False),
    ('completed', 'loan', True), ('cancelled', 'credit_sale', True),
])
def test_agreement_commitments_remain_separate(inventory, status, deal_type, available):
    x = inventory
    a = x.Asset(organization_id=1)
    x.session.add(x.Contract(asset=a, quantity=1, status=status, deal_type=deal_type))
    x.session.commit()
    assert bool(x.query().all()) is available


def test_voided_sale_releases_stock_and_partial_stock_is_available(inventory):
    x = inventory
    a = x.Asset(organization_id=1, kind='phone', quantity_total=5)
    x.session.add_all([x.Sale(asset=a, quantity=3, status='completed'), x.Sale(asset=a, quantity=3, status='voided')])
    x.session.commit()
    assert x.query(kind='other').one().id == a.id
    x.session.add(x.Contract(asset=a, quantity=2, status='active'))
    x.session.commit()
    assert x.query().count() == 0


def test_inventory_search_by_year_and_identifier(inventory):
    x = inventory
    a = x.Asset(organization_id=1, identifier='TEST-908', vehicle_year=2022)
    x.session.add(a)
    x.session.commit()
    assert x.query(q='2022').one().id == a.id
    assert x.query(q='TEST-908').one().id == a.id
    assert x.query(kind='motorcycle').count() == 0


def test_payload_uses_real_photo_and_preserves_zero_mileage():
    env = dict(
        current_user=SimpleNamespace(role='sales'),
        has_permission=lambda user, permission: False,
        asset_kind_label=lambda _: 'Carro',
        money_decimal=lambda v: Decimal(v or 0).quantize(Decimal('.01'), rounding=ROUND_HALF_UP),
        Decimal=Decimal, url_for=lambda endpoint, **kw: endpoint + '?' + '&'.join(f'{k}={v}' for k, v in kw.items()),
    )
    payload = production_function('_sale_asset_payload', env)
    a = SimpleNamespace(id=1, kind='car', name='QA', brand='', model='', identifier='QA-1', serial_number='',
        vehicle_year=2022, mileage=0, available_quantity=1, quantity_total=1,
        estimated_value=Decimal('100'), sale_price=Decimal('125'), investments=[], image_mime=None, image_updated_at=None)
    item = payload(a)
    assert item['mileage'] == 0
    assert item['image_url'] == item['full_image_url'] == item['photo_upload_url'] == ''
    a.image_mime = 'image/webp'
    a.image_updated_at = datetime(2026, 10, 5, 1, 0, 0, 123456)
    assert '123456' in payload(a)['image_url']
    assert 'thumb=1' in payload(a)['image_url']
    assert 'thumb=' not in payload(a)['full_image_url']


def test_photo_endpoint_requires_sales_and_inventory_write_permissions():
    tree = ast.parse(MAIN.read_text(encoding='utf-8'))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'sale_asset_photo')
    decorators = [ast.unparse(d) for d in fn.decorator_list]
    assert "permission_required('inventory.manage')" in decorators
    assert "permission_required('sales.manage')" in decorators
    assert 'login_required' in decorators
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'scoped_asset' for n in ast.walk(fn))


def test_photo_optimizer_and_invalid_upload():
    from PIL import Image
    env = dict(io=io, ASSET_IMAGE_SIZE=(1169, 780), ASSET_THUMB_SIZE=(360, 240), ASSET_IMAGE_MAX_BYTES=12*1024*1024)
    production_function('_encode_asset_image', env)
    upload = production_function('read_asset_image_upload', env)
    source = io.BytesIO()
    Image.new('RGB', (400, 600), (90, 120, 160)).save(source, 'JPEG')
    class Upload(io.BytesIO):
        filename = 'qa.jpg'
    image, mime, thumb = upload(Upload(source.getvalue()))
    assert mime == 'image/webp'
    assert Image.open(io.BytesIO(image)).size == (1169, 780)
    assert Image.open(io.BytesIO(thumb)).size == (360, 240)
    with pytest.raises(ValueError):
        upload(Upload(b'not an image'))


def test_release_versions_and_assets_are_coherent():
    config = (ROOT/'config.py').read_text(encoding='utf-8')
    assert 'APP_VERSION = "1.25.2"' in config
    assert 'ASSET_VERSION = "1.25.2-ui-v66"' in config
    assert (ROOT/'VERSION.txt').read_text().strip() == '1.25.2'
    for path in ['cuotago/templates/base.html', 'cuotago/static/js/app.js', 'cuotago/static/service-worker.js']:
        assert '1.25.2-ui-v66' in (ROOT/path).read_text(encoding='utf-8')
    worker = (ROOT/'cuotago/static/service-worker.js').read_text(encoding='utf-8')
    for file in ['css/sales.css', 'js/sales.js']:
        assert (ROOT/'cuotago/static'/file).is_file()
        assert '/static/'+file in worker
    css = (ROOT/'cuotago/static/css/sales.css').read_text(encoding='utf-8')
    assert '.sales-module [hidden] { display: none !important; }' in css
    form = (ROOT/'cuotago/templates/sales/form.html').read_text(encoding='utf-8')
    assert 'selected_asset_payload' in form and 'request_key' in form and 'csrf_token' in form
    assert 'sales-showroom' not in (ROOT/'cuotago/templates/sales/list.html').read_text(encoding='utf-8')
