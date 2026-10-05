"""Launcher/heading regressions. Uses real templates, no server or database."""
import html
import re
import runpy
from pathlib import Path

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
MODULES = runpy.run_path(str(ROOT / 'cuotago/module_catalog.py'))['MODULE_CATALOG']

@pytest.fixture
def templates():
    env = Environment(
        loader=ChoiceLoader([
            DictLoader({'base.html': '{% block styles %}{% endblock %}{% block content %}{% endblock %}'}),
            FileSystemLoader(ROOT / 'cuotago/templates'),
        ]),
        autoescape=True, undefined=StrictUndefined,
    )
    env.globals.update(
        url_for=lambda endpoint, **kwargs: '/' + endpoint,
        can=lambda permission: True,
        config={'ASSET_VERSION': 'qa-build'},
        money=lambda value: str(value),
    )
    return env


def home(templates, **overrides):
    context = dict(modules=MODULES, module_status={}, show_home_status=True,
                   receivable=123, overdue_total=12, due_today_count=1, reminder_count=3)
    context.update(overrides)
    return templates.get_template('dashboard.html').render(**context)


def test_pwa_prompt_and_scoped_stylesheet(templates):
    rendered = home(templates)
    assert '<h1>\u00bfQu\u00e9 quieres hacer?</h1>' in rendered
    assert 'pwa-home-heading' in rendered
    assert 'css/home.css' in (ROOT / 'cuotago/templates/dashboard.html').read_text()
    assert 'css/home.css' not in (ROOT / 'cuotago/templates/base.html').read_text()


def test_module_descriptions_come_from_same_catalog(templates):
    rendered = html.unescape(home(templates))
    for module in MODULES:
        assert module['name'] in rendered
        assert module['home_description'] in rendered
    assert len(re.findall(r'<small class="module-description"', rendered)) == len(MODULES)


def test_live_desktop_statuses_are_reused(templates):
    rendered = html.unescape(home(templates, module_status={
        'agreements': {'kind': 'small', 'text': 'Crear y gestionar \u00b7 7 activos'},
        'sales': {'kind': 'small', 'text': '4 ventas este mes'},
    }))
    assert '<small class="module-description">Crear y gestionar \u00b7 7 activos</small>' in rendered
    assert '<small class="module-description">4 ventas este mes</small>' in rendered


@pytest.mark.parametrize('kind,text', [('badge-danger', '3 vencidos'), ('badge-warning', '2 hoy')])
def test_alert_is_preserved_alongside_description(templates, kind, text):
    collection = next(m for m in MODULES if m['slug'] == 'collections')
    rendered = html.unescape(home(templates, modules=[collection], module_status={
        'collections': {'kind': kind, 'text': text},
    }))
    assert 'module-description module-description-pwa' in rendered
    assert collection['home_description'] in rendered
    assert f'class="module-badge {kind}">{text}</span>' in rendered


def test_restricted_modules_and_no_collection_footer(templates):
    selected = [m for m in MODULES if m['slug'] == 'sales']
    rendered = home(templates, modules=selected, show_home_status=False)
    assert rendered.count('class="module-card"') == 1
    assert 'home-status' not in rendered
    assert 'Agenda de cobranza' not in rendered
    assert 'main.contracts' not in rendered


@pytest.mark.parametrize('title,create,receipt_id', [
    ('Ventas', True, None), ('Nueva venta', False, None), ('CGV-1-000001', False, 1),
])
def test_sales_header_has_shared_icon_and_accessible_actions(templates, title, create, receipt_id):
    component = templates.get_template('sales/_components.html').module
    rendered = str(component.heading(title, 'QA', '/', create, receipt_id))
    assert 'data-module-icon="sales"' in rendered
    assert 'sls-context-icon' in rendered
    assert title in rendered
    if create:
        assert 'aria-label="Nueva venta"' in rendered
    if receipt_id:
        assert 'aria-label="Descargar PDF del cliente"' in rendered


def test_home_css_and_service_worker_stay_in_sync():
    path = ROOT / 'cuotago/static/css/home.css'
    assert path.is_file()
    assert "'/static/css/home.css'" in (ROOT / 'cuotago/static/service-worker.js').read_text()
    css = path.read_text()
    assert 'html.is-standalone-app body.dashboard-home' in css
    assert 'module-description-pwa { display:none!important; }' in css
    assert 'white-space:normal' in css
    assert 'overflow:visible' in css
