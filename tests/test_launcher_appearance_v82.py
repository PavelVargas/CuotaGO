"""UI82 scope and integration contracts. No Flask server or database needed."""
from pathlib import Path
from types import SimpleNamespace as NS
from dealer_fixtures import template_env

ROOT = Path(__file__).resolve().parents[1]


def text(path):
    return (ROOT/path).read_text(encoding='utf-8')


def test_single_bootstrap_runs_before_styles_without_remote_assets():
    base = text('cuotago/templates/base.html')
    assert base.index("{% include '_launcher_preferences.html' %}") < base.index('css/app.css')
    assert base.index('css/layout-v79.css') < base.index('css/launcher-v82.css')
    assert 'icons82' in base
    script = text('cuotago/templates/_launcher_preferences.html')
    assert 'fetch(' not in script and 'Notification' not in script
    assert 'setInterval' not in script


def test_old_size_handler_cannot_overwrite_new_preferences():
    app = text('cuotago/static/js/app.js')
    assert 'applyPwaLauncherSize' not in app
    assert 'data-launcher-size-range' not in app


def test_new_css_is_cached_with_the_same_build():
    worker = text('cuotago/static/service-worker.js')
    assert "'/static/css/launcher-v82.css'" in worker
    assert '-restore81-icons82' in worker


def test_preview_is_four_columns_and_overrides_are_home_scoped():
    css = text('cuotago/static/css/launcher-v82.css')
    assert 'grid-template-columns: repeat(4, minmax(0, 1fr))' in css
    assert 'repeat(3' not in css
    assert 'border-radius: var(--cg-launcher-radius)' in css
    assert 'body.cg-layout-v79.dashboard-home section.dashboard-launcher-v3' in css
    for protected in ['.workspace-topbar-v75', '.sales-page', '.reports-page', '.contracts-page', '.home-status']:
        assert protected not in css


def test_settings_controls_are_visible_for_every_account_and_do_not_submit():
    for permissions in (set(), {'collections.view'}):
        env = template_env(real_base=True, permissions=permissions)
        env.globals['current_user'].organization.currency = 'DOP'
        env.globals['request'] = NS(blueprint='main', endpoint='main.settings', method='GET')
        rendered = env.get_template('settings/index.html').render()
        assert rendered.count('id="cgLauncherSize"') == 1
        assert rendered.count('id="cgLauncherRadius"') == 1
        assert rendered.count('data-launcher-reset') >= 1
        assert 'type="button" data-launcher-reset' in rendered
        assert 'min="16" max="36"' in rendered
        assert rendered.count('class="cg-launcher-sample-v82"') == 4
        assert 'settings-account-card' in rendered
