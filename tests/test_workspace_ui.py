"""UI contract for the compact dealer workbench introduced in ui-v75."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_internal_modules_use_workspace_shell_but_home_is_exempt():
    base = (ROOT / 'cuotago/templates/base.html').read_text(encoding='utf-8')
    assert 'css/workspace.css' in base
    assert 'workbench-shell-v75' in base
    assert "request.endpoint not in ['main.dashboard','admin.dashboard']" in base
    assert 'workspace-topbar-v75' in base
    assert 'workspace-module-nav-v75' in base
    worker = (ROOT / 'cuotago/static/service-worker.js').read_text(encoding='utf-8')
    assert "'/static/css/workspace.css'" in worker


def test_workspace_is_compact_and_not_a_width_100_patch():
    css = (ROOT / 'cuotago/static/css/workspace.css').read_text(encoding='utf-8')
    assert '--ws-topbar-h:42px' in css
    assert '--ws-page-max:1600px' in css
    assert 'workspace-module-nav-v75' in css
    assert 'border-radius:0!important' in css
    assert 'repeat(auto-fill,minmax(300px,370px))' in css
    assert 'repeat(auto-fill,minmax(320px,390px))' in css


def test_inventory_is_dense_register_with_kind_and_brand_filters():
    template = (ROOT / 'cuotago/templates/assets/list.html').read_text(encoding='utf-8')
    assert 'name="brand"' in template
    assert 'name="kind"' in template
    assert 'brand_options' in template
    assert 'inventory-list-v75' in template
    assert 'inventory-item-v75' in template
    assert 'inventory-product-card-v18' not in template
    assert 'Placa' in template and 'Existencia' in template and 'Potencial' in template
    main = (ROOT / 'cuotago/main.py').read_text(encoding='utf-8')
    assert 'kind = request.args.get("kind", "").strip()' in main
    assert 'query = query.filter(Asset.kind == kind)' in main


def test_vehicle_detail_keeps_natural_photo_ratio_without_row_stretch():
    css = (ROOT / 'cuotago/static/css/dealer.css').read_text(encoding='utf-8')
    assert '.dlr-unit-hero > .dlr-hero-media' in css
    assert 'align-self:start' in css
    assert 'aspect-ratio:1169 / 780' in css
    assert '.dlr-photo.is-large.is-device-large' in css
