"""Strict rendering of one-page editor and quantity-accurate print documents."""
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from dealer_fixtures import template_env
from test_v83_templates import context
from v83_harness import module
ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('kind',['order','conduce','receipt'])
def test_documents_render_and_hide_costs_for_logistics(kind):
    d,ctx,_=context()
    try:
        order=ctx['order'];order.lines[0].unit_cost=1234567
        receipt=dict(id=1,code='RC-000001',date=datetime(2026,10,19,20),units=1,entries=[dict(line_id=order.lines[0].id,quantity=1)]) if kind=='receipt' else None
        rows=[dict(line=order.lines[0],quantity=1 if receipt else 2)]
        env=template_env(real_base=True)
        html=env.get_template('operations/order_print.html').render(**dict(ctx,kind=kind,receipt=receipt,
            print_rows=rows,printed_at=datetime.now()))
        assert 'window.print' not in html # external script, no inline handler
        assert 'data-print' in html and 'purchase-print-v84.css' in html
        if kind!='order':assert '1,234,567' not in html and 'Costo unitario' not in html
        if kind=='receipt':assert 'RC-000001' in html and 'Total de unidades</span><strong>1' in html
        if kind=='conduce':assert 'no acredita' in html and 'Total de unidades</span><strong>2' in html
    finally:d.s.close();d.engine.dispose()


def test_editor_has_single_screen_three_actions_and_safe_photo_markup():
    d,ctx,_=context()
    try:
        env=template_env(real_base=True)
        ctx.update(order=None,editor_rows=[],assets=[dict(id=d.a.id,name='</script><img src=x onerror=bad()>',cost='100',kind='car',photo='')])
        html=env.get_template('operations/order_new.html').render(**ctx)
        assert 'data-order-wizard' not in html and 'data-step' not in html
        assert all(x in html for x in ['Guardar borrador','Descartar','Confirmar orden','enctype="multipart/form-data"'])
        assert '</script><img src=x onerror=bad()>' not in html
        assert 'photo_NEWKEY' in html
    finally:d.s.close();d.engine.dispose()


def test_style_scope_preserves_home_and_input_boundaries():
    css=(ROOT/'cuotago/static/css/workspace-polish-v84.css').read_text()
    assert 'body.workbench-shell-v75 .page-shell' in css
    assert 'input {' not in css and 'outline:0' not in css
    base=(ROOT/'cuotago/templates/base.html').read_text()
    assert "request.endpoint not in ['main.dashboard','admin.dashboard'] %}<link" in base
    ui=(ROOT/'cuotago/static/css/launcher-v82.css').read_text()
    assert 'repeat(4, minmax(0, 1fr))' in ui and 'repeat(3' not in ui
