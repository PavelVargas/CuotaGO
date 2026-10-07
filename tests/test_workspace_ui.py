"""UI contract for the dense module workbench introduced in ui-v74."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_internal_modules_use_workspace_stylesheet_but_home_is_exempt():
    base = (ROOT / 'cuotago/templates/base.html').read_text(encoding='utf-8')
    assert 'css/workspace.css' in base
    assert 'workbench-shell-v74' in base
    assert "request.endpoint not in ['main.dashboard','admin.dashboard']" in base
    worker = (ROOT / 'cuotago/static/service-worker.js').read_text(encoding='utf-8')
    assert "'/static/css/workspace.css'" in worker


def test_workspace_removes_desktop_document_width_and_compacts_chrome():
    css = (ROOT / 'cuotago/static/css/workspace.css').read_text(encoding='utf-8')
    assert '.content-page.narrow-page' in css
    assert 'max-width: none !important' in css
    assert '--ws-header-h: 46px' in css
    assert '.brand-word-shell' in css
    assert '.sls-workspace' in css
    assert '.dlr-header' in css


def test_inventory_is_a_dense_list_with_brand_filter():
    template = (ROOT / 'cuotago/templates/assets/list.html').read_text(encoding='utf-8')
    assert 'name="brand"' in template
    assert 'brand_options' in template
    assert 'inventory-table-v74' in template
    assert 'inventory-line-v74' in template
    assert 'inventory-product-card-v18' not in template
    assert 'Placa' in template and 'Existencia' in template and 'Potencial' in template


def test_vehicle_detail_uses_natural_photo_ratio_without_row_stretch():
    css = (ROOT / 'cuotago/static/css/dealer.css').read_text(encoding='utf-8')
    assert '.dlr-unit-hero > .dlr-hero-media' in css
    assert 'align-self:start' in css
    assert 'aspect-ratio:1169 / 780' in css
    assert '.dlr-photo.is-large.is-device-large' in css
