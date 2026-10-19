"""PDF rendering/text contracts; monetary service tests verify the amounts."""
import runpy
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace as N
from decimal import Decimal as D
import pytest
fitz=pytest.importorskip('fitz')
ROOT=Path(__file__).resolve().parents[1]
PDF=runpy.run_path(str(ROOT/'cuotago/pdf_reports.py'))

def sample():
 c=N(code='QA-83',organization_id=1,asset=N(name='Unidad QA'),client=N(full_name='Persona QA',phone='8095550100'),balance=D('1000'),total_amount=D('1000'),paid_total=D('0'),status='active')
 p=N(id=1,contract=c,receipt_code='CGP-1-000001',amount=D('100'),late_fee_amount=D('0'),paid_at=datetime(2026,11,1,1),payment_kind='payment',method='cash',reference='QA',note=None,voided_at=datetime(2026,11,2,1),void_reason='Correccion de prueba',reversal=N(code='CGR-1-000001'))
 args=dict(app_name='CuotaGO',business_name='Empresa QA',money=lambda n:f'RD${n:,.2f}',payment_method_label=lambda _:'Efectivo')
 return c,p,args

def test_reversed_receipt_is_obviously_not_a_live_payment():
 c,p,args=sample();raw=PDF['receipt_pdf_bytes'](**args,payment=p,registered_by=N(name='Operador QA'))
 doc=fitz.open(stream=raw,filetype='pdf');text=''.join(x.get_text() for x in doc)
 assert len(doc)==1
 for value in ('PAGO REVERTIDO','NO VIGENTE','CGR-1-000001','31/10/2026 21:00','Correccion de prueba'):assert value in text

def test_statement_preserves_reversed_history_but_current_zero_total():
 c,p,args=sample();raw=PDF['statement_pdf_bytes'](**args,client=c.client,contracts=[c],payments=[p],totals=dict(agreed=D('1000'),paid=D('0'),balance=D('1000'),late_fee=D('0')),next_item=None)
 doc=fitz.open(stream=raw,filetype='pdf');text=''.join(x.get_text() for x in doc)
 assert len(doc)==1 and 'REVERTIDO' in text and 'no suman' in text and 'RD$0.00' in text
