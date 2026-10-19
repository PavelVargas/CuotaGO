"""Restoration contract. No database or real notifications are used."""
import re
from pathlib import Path
from types import SimpleNamespace as NS
from dealer_fixtures import fixture_data, template_env
from test_layout_v79 import render_base

ROOT = Path(__file__).resolve().parents[1]
REMOVED_UI = ('css/simple-v80.css', 'js/simple-v80.js', 'js/purchases-v80.js')


def text(path):
    return (ROOT/path).read_text(encoding='utf-8')


def test_removed_ui_layer_is_not_loaded_or_precached():
    base = text('cuotago/templates/base.html')
    worker = text('cuotago/static/service-worker.js')
    for asset in REMOVED_UI:
        assert asset not in base and asset not in worker
        assert not (ROOT/'cuotago/static'/asset).exists()
    assert 'cg-simple-v80' not in base
    assert '-restore81' in base and '-restore81' in worker
    assert 'Manrope' not in base


def test_four_home_columns_are_explicit_for_pwa_and_phone():
    css = text('cuotago/static/css/layout-v79.css')
    tail = css[css.index('/* UI81 restoration contract'):]
    rules = re.findall(r'([^{}]+)\{\s*grid-template-columns:\s*([^;]+);', tail)
    assert len(rules) == 2
    for selector, declaration in rules:
        assert '.dashboard-home' in selector and '.module-grid' in selector
        assert 'repeat(4, minmax(0, 1fr)) !important' in declaration
    assert 'html.is-standalone-app' in rules[0][0]
    assert '@media screen and (max-width: 719px)' in tail


def test_desktop_navigation_is_not_hidden_in_a_disclosure():
    rendered, _ = render_base()
    assert '<nav class="workspace-module-nav-v75"' in rendered
    assert 'cg-context-menu' not in rendered
    assert 'cg-drawer-context' not in rendered


def test_agreement_fields_and_summary_are_back():
    template = text('cuotago/templates/contracts/list.html')
    for marker in ('agreements-overview-v23', 'agreement-progress-v23',
                   'contract.total_amount', 'contract.paid_total', 'contract.balance',
                   'contract.next_installment', 'contract.late_fee_balance'):
        assert marker in template
    assert 'cg-fold' not in template


def test_complete_report_sections_are_back():
    template = text('cuotago/templates/reports/index.html')
    for marker in ('capital_total', 'capital_recovered', 'profit_realized',
                   'inventory_available_value', 'direct_sales_period_profit',
                   'overdue_aging', 'overdue_attention', 'payment_method_totals'):
        assert marker in template
    assert 'data-report-tab' not in template
    assert 'cg-report-tabs' not in template


def test_full_settings_and_sound_controls_remain_available():
    template = text('cuotago/templates/settings/index.html')
    for marker in ('settings-account-card', 'settings-business-tools-v16',
                   'data-alert-tone', 'data-alert-intensity', 'data-alert-volume',
                   'data-alert-sound-preview', 'data-notification-demo'):
        assert marker in template
    assert 'cg-settings-group' not in template


def test_purchase_form_keeps_all_fields_and_inventory_detection():
    data = fixture_data()
    env = template_env(real_base=True)
    html = env.get_template('purchases/form.html').render(
        app_name='CuotaGo', form={}, assets=[data.asset], default_date='2026-10-19',
        suppliers=[NS(id=1, name='QA supplier', phone='')], rows=[dict(mode='existing',quantity=1)],
        request=NS(blueprint='main', endpoint='main.purchase_new', method='GET'),
    )
    form = re.search(r'<form[^>]+id="purchaseForm"[^>]*>(.*?)</form>', html, re.S).group(1)
    names = set(re.findall(r'\bname="([^"]+)"', form))
    assert {'csrf_token', 'purchase_date', 'reference', 'supplier_id',
            'new_supplier_name', 'new_supplier_phone', 'item_mode', 'item_asset_id',
            'item_name', 'item_kind', 'item_quantity', 'item_unit_cost', 'item_notes'} <= names
    assert 'const hasAssets = true;' in html
    assert 'data-purchase-step' not in form
    assert 'id="purchaseItems"' in form and 'id="purchaseTotalCost"' in form
