"""Home artwork contracts. No database, server, secret or production request."""
from pathlib import Path
from types import SimpleNamespace as NS
import runpy
import re
from PIL import Image
import pytest
from dealer_fixtures import template_env

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'cuotago/static'
MODULES = runpy.run_path(str(ROOT / 'cuotago/module_catalog.py'))['MODULE_CATALOG']
ART = ('agreements', 'sales', 'collections', 'clients', 'purchases', 'inventory',
       'calendar', 'reports', 'expenses', 'documents')


def home(modules=MODULES):
    env = template_env(real_base=True)
    env.globals['request'] = NS(blueprint='main', endpoint='main.dashboard', method='GET')
    return env.get_template('dashboard.html').render(
        modules=modules, module_status={}, show_home_status=True,
        receivable=100, overdue_total=20, due_today_count=1, reminder_count=2)


@pytest.mark.parametrize('name', ART)
def test_local_webp_is_small_transparent_and_square(name):
    path = STATIC / 'icons/modules-3d' / f'{name}.webp'
    assert path.stat().st_size < 24000
    with Image.open(path) as im:
        assert im.size == (256, 256)
        assert im.mode == 'RGBA'
        assert im.getpixel((0, 0))[3] == 0
        assert im.getchannel('A').getextrema() == (0, 255)


def test_all_art_is_within_budget_and_no_fonts_are_bundled():
    files = list((STATIC / 'icons/modules-3d').iterdir())
    assert {p.stem for p in files} == set(ART)
    assert all(p.suffix == '.webp' for p in files)
    assert sum(p.stat().st_size for p in files) < 180000


def test_render_keeps_actual_module_links_and_names():
    env = template_env()
    rendered = home()
    assert rendered.count('class="cg-module-image-v85"') == len(MODULES)
    for m in MODULES:
        assert f'href="{env.globals["url_for"](m["endpoint"])}"' in rendered
        assert f'<strong>{m["name"]}</strong>' in rendered
    assert 'Agenda de cobranza' in rendered
    assert 'RD$100.00' in rendered


def test_permissions_are_not_replaced_by_static_mockup_links():
    rendered = home([MODULES[1]])
    assert rendered.count('class="module-card"') == 1
    assert 'data-module-art="sales"' in rendered
    assert 'data-module-art="clients"' not in rendered


def test_macro_is_decorative_and_has_no_inline_event_handlers():
    rendered = home()
    tags = re.findall(r'<img class="cg-module-image-v85"[^>]+>', rendered)
    assert len(tags) == 10
    for tag in tags:
        assert all(a in tag for a in ('alt=""', 'width="256"', 'height="256"',
                                     'decoding="async"', 'loading="eager"'))
        assert 'onload=' not in tag and 'onerror=' not in tag


def test_new_unknown_module_uses_existing_svg_without_broken_image():
    env = template_env()
    rendered = str(env.get_template('macros/module_art.html').module.module_art('settings', 'accent-blue'))
    assert '<svg' in rendered
    assert '<img' not in rendered


@pytest.mark.parametrize('endpoint,expected', [('main.dashboard', True), ('main.settings', True),
    ('main.assets', False), ('main.contracts', False), ('main.reports', False), ('auth.login', False)])
def test_art_layer_is_only_loaded_where_it_is_used(endpoint, expected):
    env = template_env(real_base=True)
    env.globals['request'] = NS(blueprint=endpoint.split('.')[0], endpoint=endpoint, method='GET')
    rendered = env.get_template('base.html').render()
    assert ('css/launcher-3d-v85.css' in rendered) is expected
    assert ('js/launcher-3d-v85.js' in rendered) is expected


def test_settings_preview_and_original_preferences_are_preserved():
    env = template_env(real_base=True)
    env.globals['request'] = NS(blueprint='main', endpoint='main.settings', method='GET')
    env.globals['current_user'].organization.currency = 'DOP'
    rendered = env.get_template('settings/index.html').render()
    assert rendered.count('class="cg-module-image-v85"') == 4
    assert 'data-launcher-size-range' in rendered and 'data-launcher-radius-range' in rendered
    assert 'min="76" max="100"' in rendered and 'min="16" max="36"' in rendered
    assert 'data-launcher-reset' in rendered


def test_art_urls_match_service_worker_precache_build():
    worker = (STATIC / 'service-worker.js').read_text()
    for name in ART:
        assert f"'/static/icons/modules-3d/{name}.webp'" in worker
    assert "'/static/css/launcher-3d-v85.css'" in worker
    assert "'/static/js/launcher-3d-v85.js'" in worker
    assert '1.27.0-rc2-ui-v85-restore81-icons82-icons3d85' in worker
    rendered = home()
    # All home image requests use the exact same version as their stylesheet.
    versions = re.findall(r'icons/modules-3d/[^"?]+\?v=([^"&]+)', rendered)
    assert len(set(versions)) == 1
    assert versions[0].endswith('-restore81-icons82-icons3d85')


def test_no_three_columns_and_no_unrelated_screen_restyle():
    css = (STATIC / 'css/launcher-3d-v85.css').read_text()
    assert 'grid-template-columns' not in css  # Keep restored column contract.
    assert '--cg-launcher-radius' in css and '--cg-launcher-size' in css
    assert 'prefers-reduced-motion' in css and 'forced-colors' in css
    for selector in ('.reports-page', '.contract-grid', '.topbar {', 'input {', 'font-family:'):
        assert selector not in css
