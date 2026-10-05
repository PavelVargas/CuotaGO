"""Customer document privacy checks; no database or production data required."""
import ast
from dataclasses import asdict, replace
from datetime import date
from decimal import Decimal
from io import BytesIO
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cuotago_customer_receipt_test', ROOT/'cuotago/sale_documents.py')
documents = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = documents
spec.loader.exec_module(documents)


def money(value):
    return f'RD${Decimal(value):,.2f}'


@pytest.fixture
def sale():
    return SimpleNamespace(
        id=9, organization_id=1, code='CGV-1-000009', sale_date=date(2026,10,5),
        client=None, buyer_name='Cliente de prueba', buyer_phone='8090000000',
        asset=SimpleNamespace(kind='car',name='Vehiculo de prueba',brand='Marca',model='Modelo',
            identifier='QA-123',serial_number='VIN-TEST-456',vehicle_year=2020,mileage=0,
            estimated_value=Decimal('31678.91'), acquisition_origin='SECRET SUPPLIER'),
        quantity=1,unit_price=Decimal('50000'),total_amount=Decimal('50000'),
        payment_method='cash',reference='REF-PUBLIC',status='completed',
        unit_cost=Decimal('31678.91'), investment_cost=Decimal('2222.22'),
        total_cost=Decimal('33901.13'),profit_amount=Decimal('16098.87'),
        margin_percent=Decimal('47.49'),notes='SECRET INTERNAL NOTE',void_reason='SECRET VOID REASON',
    )


def receipt(sale):
    return documents.customer_sale_receipt(sale,business_name='Negocio de prueba',money=money,
        payment_method_label=lambda _: 'Efectivo')


def pdf_text(payload):
    reader=PdfReader(BytesIO(payload))
    return '\n'.join(page.extract_text() for page in reader.pages) + str(reader.metadata)


def test_allowlist_never_reads_private_values(sale):
    class Guard(SimpleNamespace):
        def __getattribute__(self,name):
            if name in {'unit_cost','total_cost','investment_cost','profit_amount','margin_percent','notes','void_reason'}:
                raise AssertionError('Private field accessed: '+name)
            return super().__getattribute__(name)
    result=receipt(Guard(**vars(sale)))
    assert not set(asdict(result)) & {'unit_cost','total_cost','investment_cost','profit_amount','margin_percent','notes','void_reason'}
    assert result.identifiers[-1]==('Kilometraje','0 km')
    assert result.total=='RD$50,000.00'


@pytest.mark.parametrize('kind', ['car','phone','motorcycle','otro'])
def test_pdf_contains_sale_price_but_no_internal_financials(sale,kind):
    sale.asset.kind=kind
    payload=documents.sale_receipt_pdf_bytes(receipt(sale))
    assert payload.startswith(b'%PDF-')
    text=pdf_text(payload)
    assert 'RD$50,000.00' in text and 'Cliente de prueba' in text
    assert 'REF-PUBLIC' in text and 'CGV-1-000009' in text
    for private in ['31,678.91','2,222.22','33,901.13','16,098.87','47.49','SECRET','Costo','Utilidad','Inversiones']:
        assert private not in text
    assert sale.profit_amount==Decimal('16098.87')
    assert len(PdfReader(BytesIO(payload)).pages)==1


def test_html_receipt_does_not_have_hidden_private_data(sale):
    env=Environment(loader=FileSystemLoader(ROOT/'cuotago/templates'),autoescape=select_autoescape())
    html=env.get_template('sales/_customer_receipt.html').render(receipt=receipt(sale))
    assert 'RD$50,000.00' in html
    for forbidden in ['SECRET','31,678.91','Costo','Utilidad','Inversiones','margin_percent','data-cost']:
        assert forbidden not in html


def test_anulled_sale_is_not_presented_as_payment(sale):
    sale.status='voided'
    text=pdf_text(documents.sale_receipt_pdf_bytes(receipt(sale)))
    assert 'ANULADO' in text
    assert 'TOTAL PAGADO' not in text and 'Pago completo registrado' not in text
    assert 'SECRET VOID REASON' not in text


def test_snapshot_buyer_is_preferred(sale):
    sale.client=SimpleNamespace(full_name='Changed client name',phone='Changed phone')
    r=receipt(sale)
    assert r.buyer_name=='Cliente de prueba' and r.buyer_phone=='8090000000'


@pytest.mark.parametrize('photo', [None,b'broken-photo'])
def test_missing_or_corrupt_photo_is_nonfatal(sale,photo):
    assert 'RD$50,000.00' in pdf_text(documents.sale_receipt_pdf_bytes(receipt(sale),photo=photo))


def test_photo_is_embedded_without_metadata(sale):
    from PIL import Image
    stream=BytesIO()
    Image.new('RGB',(500,280),'gray').save(stream,format='PNG')
    reader=PdfReader(BytesIO(documents.sale_receipt_pdf_bytes(receipt(sale),photo=stream.getvalue())))
    assert len(reader.pages[0].images)==1
    assert len(reader.pages)==1


def test_long_and_xml_like_text_is_not_interpreted(sale):
    sale.buyer_name='<script>alert(1)</script> & Garcia'
    sale.asset.name='Vehiculo '+('modelo extenso '*9)
    r=replace(receipt(sale),business_name='Comercial '+('NOMBRE '*15),reference='R'*120)
    text=pdf_text(documents.sale_receipt_pdf_bytes(r))
    assert '<script>alert(1)</script> & Garcia' in text
    env=Environment(loader=FileSystemLoader(ROOT/'cuotago/templates'),autoescape=select_autoescape())
    html=env.get_template('sales/_customer_receipt.html').render(receipt=r)
    assert '<script>' not in html
    assert '&lt;script&gt;' in html


@pytest.mark.parametrize('function',['sale_receipt','sale_receipt_pdf'])
def test_document_routes_require_sales_view_and_tenant_scope(function):
    tree=ast.parse((ROOT/'cuotago/main.py').read_text())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==function)
    decorators=[ast.unparse(d) for d in node.decorator_list]
    assert 'login_required' in decorators
    assert "permission_required('sales.view')" in decorators
    assert any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='scoped_sale' for n in ast.walk(node))
    # The route must not feed an ORM model to the customer HTML or PDF.
    if function=='sale_receipt':
        call=next(n for n in ast.walk(node) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='render_template')
        assert 'sale' not in {k.arg for k in call.keywords}


def test_pdf_is_no_store_and_worker_does_not_cache_receipts():
    source=(ROOT/'cuotago/main.py').read_text()
    fn=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='sale_receipt_pdf')
    code=ast.get_source_segment(source,fn)
    assert 'private, no-store' in code and 'as_attachment=True' in code
    assert 'receipt(?:\\.pdf)?' in (ROOT/'cuotago/static/service-worker.js').read_text()
    css=(ROOT/'cuotago/static/css/sale-receipt.css').read_text()
    assert '.page-shell>*:not(.customer-print)' in css
    assert 'display:none!important' in css
    js=(ROOT/'cuotago/static/js/sales.js').read_text()
    assert 'window.print()' not in js


def test_all_templates_parse_and_shared_ui_is_loaded_last():
    env=Environment()
    for path in (ROOT/'cuotago/templates').rglob('*.html'):
        env.parse(path.read_text())
    base=(ROOT/'cuotago/templates/base.html').read_text()
    assert base.index('css/ui.css') > base.index('{% block styles %}')
    assert 'ui-v67' in base
    assert 'zoom:' not in (ROOT/'cuotago/static/css/ui.css').read_text()


def test_print_document_cannot_start_transparent_animation():
    css=(ROOT/'cuotago/static/css/sale-receipt.css').read_text()
    assert 'animation:none!important' in css
    assert 'opacity:1!important' in css
    assert 'content-visibility:visible!important' in css
